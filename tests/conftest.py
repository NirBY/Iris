import base64

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setenv("IRIS_SECRET_KEY", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("IRIS_PUBLIC_BASE_URL", "http://localhost:8080/")
    monkeypatch.setenv("IRIS_DATA_DIR", str(tmp_path_factory.mktemp("data")))
    get_settings.cache_clear()
