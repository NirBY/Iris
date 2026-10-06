import pytest
from cryptography.exceptions import InvalidTag

from app.security.crypto import decrypt, encrypt

KEY = b"k" * 32


def test_round_trip_unicode() -> None:
    assert decrypt(KEY, encrypt(KEY, "סוד-secret")) == "סוד-secret"


def test_nonce_is_random() -> None:
    assert encrypt(KEY, "x") != encrypt(KEY, "x")


def test_wrong_key_or_tamper_fails() -> None:
    tok = encrypt(KEY, "x")
    with pytest.raises(InvalidTag):
        decrypt(b"j" * 32, tok)
