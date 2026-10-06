import base64

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setenv("IRIS_SECRET_KEY", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("IRIS_PUBLIC_BASE_URL", "http://localhost:8080/")
    monkeypatch.setenv("IRIS_DATA_DIR", str(tmp_path_factory.mktemp("data")))
    get_settings.cache_clear()


@pytest.fixture
async def app_client(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Logged-in client against the real app (migrated temp DB, lifespan running)."""
    import asyncio

    import httpx

    from app import main
    from app.db.migrate import upgrade_head

    monkeypatch.setenv("IRIS_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("IRIS_ADMIN_PASSWORD", "correct-horse")
    get_settings.cache_clear()
    await asyncio.to_thread(upgrade_head)
    app = main.create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "correct-horse"})
        assert r.status_code == 200
        c.app = app  # type: ignore[attr-defined]
        yield c
