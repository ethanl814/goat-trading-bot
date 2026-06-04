# bot/framework/venues/kalshi/auth.py
"""Kalshi request signing (RSA-PSS).

Kalshi authenticates every request with three headers:
    KALSHI-ACCESS-KEY        the API key id
    KALSHI-ACCESS-TIMESTAMP  unix time in milliseconds
    KALSHI-ACCESS-SIGNATURE  base64( RSA-PSS-SHA256( timestamp + METHOD + path ) )

The signed `path` is the request path WITHOUT query params (e.g.
`/trade-api/v2/markets`), and RSA-PSS uses MGF1(SHA256) with salt length =
digest length. See docs.kalshi.com/getting_started/api_keys.
"""
from __future__ import annotations

import base64
import time
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


@lru_cache(maxsize=4)
def load_private_key(path: str):
    data = Path(path).expanduser().read_bytes()
    return serialization.load_pem_private_key(data, password=None)


def sign(private_key, message: str) -> str:
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def auth_headers(key_id: str, private_key, method: str, path: str) -> dict[str, str]:
    ts = str(int(time.time() * 1000))
    message = ts + method.upper() + path
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": sign(private_key, message),
    }
