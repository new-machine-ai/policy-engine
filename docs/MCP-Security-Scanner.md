# MCP Security Scanner

`mcp-security-scanner/` is a sibling package next to `policy-engine/`. It keeps
MCP-specific supply-chain and gateway logic out of the stdlib policy core while
reusing `policy_engine.BaseKernel.evaluate()` as the Policy Decision Point.

## What It Covers

- Tool poisoning in MCP tool descriptions: hidden unicode, comments, encoded
  payloads, and instruction-like metadata.
- Schema abuse: overly permissive schemas, suspicious required fields, and
  instruction-bearing defaults.
- Cross-server impersonation and typosquatting.
- Rug-pull detection using SHA-256 fingerprints for tool definitions.
- Runtime MCP gateway checks for tool allow/deny, blocked argument patterns,
  human approval, call budgets, and contextual rules such as market hours.

## Quick Commands

```bash
PYTHONPATH=policy-engine/src:mcp-security-scanner/src \
  python -m mcp_security_scanner.cli scan \
  mcp-security-scanner/examples/poisoned_mcp_config.json --format json
```

```bash
PYTHONPATH=policy-engine/src:mcp-security-scanner/src \
  python -m mcp_security_scanner.cli fingerprint \
  mcp-security-scanner/examples/poisoned_mcp_config.json
```

Audit output stores hashes and metadata only; raw prompts, raw tool arguments,
raw schemas, and hidden payload text are not persisted.

