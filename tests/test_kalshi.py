# tests/test_kalshi.py
"""Kalshi venue: RSA-PSS signing correctness, candle->Bar conversion, and spec.

No network or real credentials — signing is verified against a freshly generated
key pair, and the candle parser runs on sample JSON shaped like Kalshi's response.
"""
import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from bot.framework.events import Bar
from bot.framework.instruments import AssetClass, PriceKind
from bot.framework.venues.kalshi import adapter as kadapter
from bot.framework.venues.kalshi import auth
from bot.framework.venues.kalshi import history


def test_sign_is_verifiable_rsa_pss():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    msg = "1700000000000" + "GET" + "/trade-api/v2/markets"
    sig_b64 = auth.sign(key, msg)
    # the public key must verify the signature under the same PSS params
    key.public_key().verify(
        base64.b64decode(sig_b64),
        msg.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )  # raises InvalidSignature if wrong


def test_auth_headers_shape():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    h = auth.auth_headers("kid-123", key, "get", "/trade-api/v2/markets")
    assert set(h) == {"KALSHI-ACCESS-KEY", "KALSHI-ACCESS-TIMESTAMP", "KALSHI-ACCESS-SIGNATURE"}
    assert h["KALSHI-ACCESS-KEY"] == "kid-123"
    assert h["KALSHI-ACCESS-TIMESTAMP"].isdigit()


def test_build_spec_is_probability_long_only():
    spec = kadapter.build_spec("KXTEST-123")
    assert spec.asset_class is AssetClass.PREDICTION_MARKET
    assert spec.price_kind is PriceKind.PROBABILITY
    assert spec.long_only and not spec.shortable
    assert spec.settle_low == 0.0 and spec.settle_high == 1.0


def test_candle_ohlc_prefers_traded_price():
    candle = {"price": {"open": "0.40", "high": "0.55", "low": "0.38", "close": "0.50"}}
    assert history._ohlc(candle) == (0.40, 0.55, 0.38, 0.50)


def test_candle_ohlc_handles_dollars_suffix():
    # Kalshi's real response uses *_dollars keys
    candle = {"price": {"open_dollars": "0.30", "high_dollars": "0.85",
                        "low_dollars": "0.29", "close_dollars": "0.46"}}
    assert history._ohlc(candle) == (0.30, 0.85, 0.29, 0.46)


def test_candle_ohlc_falls_back_to_bid_ask_mid():
    # no trades this interval -> mid of yes bid/ask
    candle = {"price": {"close": None},
              "yes_bid": {"open": "0.40", "close": "0.44"},
              "yes_ask": {"open": "0.50", "close": "0.46"}}
    o, h, l, c = history._ohlc(candle)
    assert c == pytest.approx(0.45)  # (0.44 + 0.46)/2
    assert o == pytest.approx(0.45)  # (0.40 + 0.50)/2


def test_candle_ohlc_none_when_no_data():
    assert history._ohlc({"price": {"close": None}}) is None