import base64
from datetime import timedelta

import pytest

from prompt_injection import InMemoryNonceStore, MCPMessageSigner, MCPSignedEnvelope


def test_sign_verify_and_replay_rejection():
    signer = MCPMessageSigner(MCPMessageSigner.generate_key())
    envelope = signer.sign_message('{"method":"tools/call"}', sender_id="client-a")

    first = signer.verify_message(envelope)
    second = signer.verify_message(envelope)

    assert first.is_valid
    assert first.payload == envelope.payload
    assert first.sender_id == "client-a"
    assert not second.is_valid
    assert "Duplicate nonce" in second.failure_reason


def test_tamper_and_time_window_failures():
    signer = MCPMessageSigner(MCPMessageSigner.generate_key(), replay_window=timedelta(seconds=1))
    envelope = signer.sign_message("payload")
    tampered = MCPSignedEnvelope(
        payload="changed",
        nonce=envelope.nonce,
        timestamp=envelope.timestamp,
        signature=envelope.signature,
        sender_id=envelope.sender_id,
    )
    expired = MCPSignedEnvelope(
        payload=envelope.payload,
        nonce="new-nonce",
        timestamp=envelope.timestamp - timedelta(minutes=10),
        signature=envelope.signature,
        sender_id=envelope.sender_id,
    )

    assert signer.verify_message(tampered).failure_reason == "Invalid signature."
    assert "timestamp outside" in signer.verify_message(expired).failure_reason


def test_base64_key_and_invalid_key_rejection():
    key = base64.b64encode(MCPMessageSigner.generate_key()).decode("ascii")
    signer = MCPMessageSigner.from_base64_key(key)
    assert isinstance(signer, MCPMessageSigner)

    with pytest.raises(ValueError):
        MCPMessageSigner(b"too-short")
    with pytest.raises(ValueError):
        MCPMessageSigner.from_base64_key("")


def test_nonce_store_cleanup_and_bound():
    store = InMemoryNonceStore(max_entries=1)
    signer = MCPMessageSigner(
        MCPMessageSigner.generate_key(),
        replay_window=timedelta(milliseconds=1),
        nonce_cache_cleanup_interval=timedelta(milliseconds=1),
        nonce_store=store,
    )
    first = signer.sign_message("one")
    second = signer.sign_message("two")

    assert signer.verify_message(first).is_valid
    assert signer.verify_message(second).is_valid
    assert store.count() == 1
    assert signer.cleanup_nonce_cache() >= 0
