"""Per-framework adapters. Import the specific submodule you need.

Each adapter lazily imports its framework dep so a missing optional dep does
not break `import policy_engine`.
"""
