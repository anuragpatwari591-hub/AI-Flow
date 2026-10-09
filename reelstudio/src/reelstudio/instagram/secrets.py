"""Encrypt tokens at rest. The key comes from RS_SECRET_KEY (or a secret manager injecting it); never from code."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings


class SecretsError(Exception):
    pass


class TokenCipher:
    def __init__(self, key: str | None = None) -> None:
        key = key if key is not None else get_settings().secret_key
        if not key:
            raise SecretsError("RS_SECRET_KEY is not set; refusing to store tokens unencrypted")
        try:
            self._f = Fernet(key.encode())
        except ValueError as e:
            raise SecretsError("RS_SECRET_KEY is not a valid Fernet key") from e

    def encrypt(self, token: str) -> str:
        return self._f.encrypt(token.encode()).decode()

    def decrypt(self, blob: str) -> str:
        try:
            return self._f.decrypt(blob.encode()).decode()
        except InvalidToken as e:
            raise SecretsError("stored token cannot be decrypted with the current RS_SECRET_KEY") from e
