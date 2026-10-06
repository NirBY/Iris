import base64

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_and_slash_strip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IRIS_WORKERS")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.public_base_url == "http://localhost:8080"
    assert s.workers == 3
    assert len(s.key_bytes) == 32


def test_missing_secret_key_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IRIS_SECRET_KEY")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("bad", ["not-base64!!", base64.b64encode(b"short").decode()])
def test_bad_secret_key(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("IRIS_SECRET_KEY", bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
