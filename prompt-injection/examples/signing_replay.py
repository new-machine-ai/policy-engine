# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Message signing and replay rejection example."""

from __future__ import annotations

from prompt_injection import MCPMessageSigner


def main() -> None:
    signer = MCPMessageSigner(MCPMessageSigner.generate_key())
    envelope = signer.sign_message('{"jsonrpc":"2.0","method":"tools/call"}', sender_id="client-a")
    print(signer.verify_message(envelope).to_dict())
    print(signer.verify_message(envelope).to_dict())


if __name__ == "__main__":
    main()
