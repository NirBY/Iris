"""AES-256-GCM encryption for secrets at rest (random 12-byte nonce per value)."""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12


def encrypt(key: bytes, plaintext: str) -> str:
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt(key: bytes, token: str) -> str:
    raw = base64.b64decode(token)
    return AESGCM(key).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], None).decode()
