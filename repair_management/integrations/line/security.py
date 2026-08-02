from __future__ import annotations

import base64
import hashlib
import hmac


def verify_line_signature(raw_body: bytes, signature: str, channel_secret: str) -> bool:
    """Return True when a LINE webhook signature matches the exact raw body."""
    if not raw_body or not signature or not channel_secret:
        return False

    digest = hmac.new(
        channel_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)

