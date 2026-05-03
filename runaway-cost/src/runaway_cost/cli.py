# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""CLI for runaway-cost controls."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .budget import BudgetPolicy, BudgetTracker
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .guard import RunawayCostGuard
from .rate_limit import SlidingWindowRateLimiter
from .retry import RetryExhausted, retry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runaway-cost",
        description="Rate limits, budgets, retries, and circuit breakers for runaway cost control.",
    )
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser("check", help="Evaluate a guarded attempt")
    check.add_argument("--agent-id", required=True)
    check.add_argument("--session-id", required=True)
    check.add_argument("--operation", required=True)
    check.add_argument("--tokens", type=int, default=0)
    check.add_argument("--cost-usd", type=float, default=0.0)
    check.add_argument("--duration-seconds", type=float, default=0.0)
    check.add_argument("--format", choices=["json", "markdown"], default="markdown")

    budget = subparsers.add_parser("budget", help="Budget commands")
    budget_sub = budget.add_subparsers(dest="budget_command")
    record = budget_sub.add_parser("record", help="Record budget usage")
    record.add_argument("--agent-id", required=True)
    record.add_argument("--tokens", type=int, default=0)
    record.add_argument("--tool-call", action="store_true")
    record.add_argument("--cost-usd", type=float, default=0.0)
    record.add_argument("--duration-seconds", type=float, default=0.0)
    record.add_argument("--max-tokens", type=int, default=1000)
    record.add_argument("--max-tool-calls", type=int, default=10)
    record.add_argument("--max-cost-usd", type=float, default=1.0)
    record.add_argument("--format", choices=["json", "markdown"], default="markdown")

    rate_limit = subparsers.add_parser("rate-limit", help="Rate limit commands")
    rate_sub = rate_limit.add_subparsers(dest="rate_command")
    acquire = rate_sub.add_parser("acquire", help="Acquire one sliding-window call")
    acquire.add_argument("--agent-id", required=True)
    acquire.add_argument("--limit", type=int, default=10)
    acquire.add_argument("--window-seconds", type=float, default=60.0)
    acquire.add_argument("--attempts", type=int, default=1)
    acquire.add_argument("--format", choices=["json", "markdown"], default="markdown")

    circuit = subparsers.add_parser("circuit", help="Circuit commands")
    circuit_sub = circuit.add_subparsers(dest="circuit_command")
    for name in ("fail", "success", "state", "reset"):
        item = circuit_sub.add_parser(name)
        item.add_argument("--agent-id", required=True)
        item.add_argument("--threshold", type=int, default=3)
        item.add_argument("--format", choices=["json", "markdown"], default="markdown")

    simulate = subparsers.add_parser("simulate-retries", help="Simulate a retry loop")
    simulate.add_argument("--max-attempts", type=int, required=True)
    simulate.add_argument("--failures", type=int, required=True)
    simulate.add_argument("--format", choices=["json", "markdown"], default="markdown")

    report = subparsers.add_parser("report", help="Print empty local guard report")
    report.add_argument("--format", choices=["json", "markdown"], default="markdown")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    try:
        if args.command == "check":
            guard = RunawayCostGuard()
            decision = guard.evaluate_attempt(
                args.agent_id,
                args.session_id,
                args.operation,
                estimated_tokens=args.tokens,
                estimated_cost_usd=args.cost_usd,
                estimated_duration_seconds=args.duration_seconds,
            )
            output = decision.to_dict()
            _print(output, args.format, _decision_markdown(output))
            return 0 if decision.allowed else 1

        if args.command == "budget" and args.budget_command == "record":
            tracker = BudgetTracker(
                BudgetPolicy(
                    max_tokens=args.max_tokens,
                    max_tool_calls=args.max_tool_calls,
                    max_cost_usd=args.max_cost_usd,
                )
            )
            tracker.record_tokens(args.tokens)
            if args.tool_call:
                tracker.record_tool_call()
            tracker.record_cost(args.cost_usd)
            tracker.record_duration(args.duration_seconds)
            output = {"agent_id": args.agent_id, "budget": tracker.status().to_dict()}
            _print(output, args.format, _budget_markdown(output))
            return 1 if output["budget"]["exceeded"] else 0

        if args.command == "rate-limit" and args.rate_command == "acquire":
            limiter = SlidingWindowRateLimiter(max_calls_per_window=args.limit, window_size=args.window_seconds)
            if args.attempts <= 0:
                raise ValueError("attempts must be positive")
            results = [limiter.try_acquire(args.agent_id) for _ in range(args.attempts)]
            allowed = all(results)
            output = {
                "agent_id": args.agent_id,
                "allowed": allowed,
                "attempts": args.attempts,
                "remaining": limiter.get_remaining_budget(args.agent_id),
                "call_count": limiter.get_call_count(args.agent_id),
            }
            _print(output, args.format, _rate_markdown(output))
            return 0 if allowed else 1

        if args.command == "circuit":
            breaker = CircuitBreaker(args.agent_id, CircuitBreakerConfig(failure_threshold=args.threshold))
            if args.circuit_command == "fail":
                breaker.record_failure()
            elif args.circuit_command == "success":
                breaker.record_success()
            elif args.circuit_command == "reset":
                breaker.reset()
            output = {
                "agent_id": args.agent_id,
                "state": breaker.get_state().value,
                "failure_count": breaker.failure_count,
                "retry_after": breaker.retry_after(),
            }
            _print(output, args.format, _circuit_markdown(output))
            return 1 if output["state"] == "open" else 0

        if args.command == "simulate-retries":
            output = _simulate_retries(args.max_attempts, args.failures)
            _print(output, args.format, _retry_markdown(output))
            return 0

        if args.command == "report":
            output = RunawayCostGuard().report()
            _print(output, args.format, _report_markdown(output))
            return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 1


def _simulate_retries(max_attempts: int, failures: int) -> dict[str, Any]:
    attempts = {"count": 0}
    events = []

    @retry(max_attempts=max_attempts, backoff_base=0.0, on_retry=events.append)
    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] <= failures:
            raise RuntimeError("simulated failure")
        return "ok"

    try:
        result = flaky()
        return {
            "result": result,
            "exhausted": False,
            "attempts": attempts["count"],
            "events": [event.to_dict() for event in events],
        }
    except RetryExhausted as exc:
        return {
            "result": None,
            "exhausted": True,
            "attempts": exc.state.attempts,
            "events": [event.to_dict() for event in events],
            "last_exception": type(exc.last_exception).__name__,
        }


def _print(output: dict[str, Any], output_format: str, markdown: str) -> None:
    if output_format == "json":
        print(json.dumps(output, indent=2))
    else:
        print(markdown)


def _decision_markdown(output: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Runaway Cost Decision",
            "",
            f"- Allowed: {output['allowed']}",
            f"- Agent: {output['agent_id']}",
            f"- Operation: {output['operation']}",
            f"- Reason: {output['reason']}",
            f"- Circuit: {output['circuit_state']}",
        ]
    )


def _budget_markdown(output: dict[str, Any]) -> str:
    budget = output["budget"]
    return "\n".join(
        [
            "# Budget Status",
            "",
            f"- Agent: {output['agent_id']}",
            f"- Exceeded: {budget['exceeded']}",
            f"- Warning: {budget['warning']}",
            f"- Reasons: {', '.join(budget['reasons']) or 'none'}",
        ]
    )


def _rate_markdown(output: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Rate Limit",
            "",
            f"- Agent: {output['agent_id']}",
            f"- Allowed: {output['allowed']}",
            f"- Remaining: {output['remaining']}",
        ]
    )


def _circuit_markdown(output: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Circuit",
            "",
            f"- Agent: {output['agent_id']}",
            f"- State: {output['state']}",
            f"- Failures: {output['failure_count']}",
        ]
    )


def _retry_markdown(output: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Retry Simulation",
            "",
            f"- Exhausted: {output['exhausted']}",
            f"- Attempts: {output['attempts']}",
            f"- Events: {len(output['events'])}",
        ]
    )


def _report_markdown(output: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Runaway Cost Report",
            "",
            f"- Budgets: {len(output['budgets'])}",
            f"- Circuits: {len(output['circuits'])}",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
