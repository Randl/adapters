"""Authenticate evidence produced outside the agent container."""

import hashlib
import hmac
import json


def sign(payload, key):
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return {
        "payload": payload,
        "signature": hmac.new(key.encode(), encoded, hashlib.sha256).hexdigest(),
    }


def verify(envelope, key, identity):
    payload = envelope["payload"]
    expected = sign(payload, key)["signature"]
    if (
        not hmac.compare_digest(expected, envelope["signature"])
        or payload["identity"] != identity
    ):
        raise ValueError("Untrusted game evidence")
    return payload
