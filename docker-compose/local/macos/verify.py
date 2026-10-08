"""Exercise the configured API without printing its key or user paths."""

import json
from pathlib import Path

import httpx

home = Path.home()
cfg = json.loads((home / ".config/mila-api/config.json").read_text())
host = cfg["host"]
if ":" in host:
    host = "[" + host + "]"
base = f"http://{host}:{cfg['port']}"
headers = {"Authorization": "Bearer " + cfg["api_key"]}
root = home / "Library/Application Support/MilaAPI"
samples = [
    (
        "ivrit-large-v3",
        "he",
        Path("/Applications/Mila.app/Contents/Resources/ConnectionTestSample.wav"),
    ),
    ("large-v3-turbo", "en", root / "engine-source/samples/jfk.wav"),
]
with httpx.Client(timeout=360, trust_env=False) as client:
    health = client.get(base + "/healthz")
    assert health.status_code == 200, "API not ready"
    assert client.get(base + "/v1/models").status_code == 401, "Authentication not enforced"
    assert client.get(base + "/v1/models", headers=headers).status_code == 200
    for model, language, sample in samples:
        if not sample.is_file():
            raise SystemExit(
                "Sample missing; install Mila in Applications and build the engine first"
            )
        response = client.post(
            base + "/v1/audio/transcriptions",
            headers=headers,
            data={"model": model, "language": language},
            files={"file": ("sample.wav", sample.read_bytes(), "audio/wav")},
        )
        assert response.status_code == 200, f"{language} test failed: HTTP {response.status_code}"
        body = response.json()
        assert body["language"] == language and body["model"] == model
        if language == "he":
            assert "שלום" in body["text"] and "עולם" in body["text"]
        else:
            assert "country" in body["text"].lower()
        print(language + ": " + body["text"])
    response = client.post(
        base + "/inference", headers=headers, files={"file": ("bad.wav", b"not audio", "audio/wav")}
    )
    assert response.status_code == 415
print("Health, authentication, Hebrew, English and invalid-upload checks passed.")
