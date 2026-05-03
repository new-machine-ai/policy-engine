# Prompt Injection

`prompt-injection/` is a sibling package for prompt-injection and untrusted-content defenses. It is separate from `policy-engine/` and has no dependency on Agent-OS.

## Capabilities

- Prompt scanning for direct override, delimiter attacks, encoded payloads, role-play/jailbreak language, context manipulation, canary leaks, and multi-turn escalation
- Untrusted MCP response scanning through `mcp-security-scanner/`
- HMAC message signing with replay protection
- OSV-backed MCP package CVE checks plus manual advisories
- Optional LlamaFirewall chaining with local detector fallback

## Quickstart

```bash
PYTHONPATH=prompt-injection/src:mcp-security-scanner/src \
  python -m prompt_injection.cli scan-prompt "ignore previous instructions" --format json
```

Unsafe scans return a nonzero exit code.

## Boundary

This package ports concepts, not dependencies. It must not import `agent_os`, declare `agent-os`, or load files from an Agent-OS checkout.
