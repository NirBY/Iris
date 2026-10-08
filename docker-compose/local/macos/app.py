"""Native, private transcription API companion for Mila's Whisper models.

This is a local integration, not an API supplied by the Mila desktop application.
Inference runs in a short-lived whisper.cpp process so idle model RAM is zero.
"""

import asyncio
import hmac
import json
import math
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

MAX_UPLOAD = 25 * 1024 * 1024
MAX_BODY = MAX_UPLOAD + 1024 * 1024
MAX_SECONDS = 300
MODELS = {
    "ivrit-large-v3": "ivrit-ai-whisper-large-v3.bin",
    "large-v3-turbo": "openai-whisper-large-v3-turbo.bin",
}
ALIASES = {
    "whisper-1": "auto",
    "ivrit-ai-whisper-large-v3": "ivrit-large-v3",
    "openai-whisper-large-v3-turbo": "large-v3-turbo",
}


class Boundary:
    """Authenticate and bound the raw body BEFORE multipart parsing/spooling."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        if scope["path"] != "/healthz":
            supplied = headers.get(b"authorization", b"")
            expected = ("Bearer " + self.token).encode()
            if not hmac.compare_digest(supplied, expected):
                return await JSONResponse({"detail": "API key required"}, 401)(scope, receive, send)
        if scope["method"] not in ("GET", "POST"):
            return await JSONResponse({"detail": "Method not allowed"}, 405)(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY:
                return await JSONResponse({"detail": "Upload exceeds 25 MiB"}, 413)(
                    scope, receive, send
                )
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def command(*args: str, deadline_seconds: float = 60) -> tuple[bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), deadline_seconds)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await asyncio.shield(proc.wait())
        raise
    if proc.returncode:
        # Never send stderr: it can contain filenames, audio data or transcripts.
        raise RuntimeError("native processing failed")
    return out, err


def sniff(head: bytes) -> bool:
    signatures = (
        (0, b"RIFF"),
        (0, b"OggS"),
        (0, b"ID3"),
        (0, b"fLaC"),
        (0, b"\x1a\x45\xdf\xa3"),
        (0, b"#!AMR"),
        (4, b"ftyp"),
    )
    return any(head[o : o + len(s)] == s for o, s in signatures) or (
        len(head) >= 2 and head[0] == 255 and head[1] & 224 == 224
    )


def parse_result(body: object) -> tuple[str, str, list[dict]]:
    if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        raise ValueError("invalid backend result")
    language = body["result"].get("language")
    segments = body.get("transcription")
    if not isinstance(language, str) or not isinstance(segments, list):
        raise ValueError("invalid backend result")
    if any(not isinstance(s, dict) or not isinstance(s.get("text"), str) for s in segments):
        raise ValueError("invalid backend segments")
    text = "".join(s["text"] for s in segments).strip()
    if not text:
        raise ValueError("no speech detected")
    return text, language, segments


def create_app(config: dict) -> FastAPI:
    root = Path(config["data_dir"])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = root / "tmp"
    tmp.mkdir(mode=0o700, exist_ok=True)
    engine = Path(config["engine"])
    models = Path(config["models_dir"])
    token = config["api_key"]
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("a strong API key is required")
    active = 0
    gate = asyncio.Lock()
    slots = asyncio.Semaphore(1)

    @asynccontextmanager
    async def lifecycle(app):
        # No audio survives a restart. Only clean this dedicated temporary directory.
        import shutil

        for path in tmp.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        yield

    app = FastAPI(
        title="Mila companion transcription API", lifespan=lifecycle, docs_url=None, redoc_url=None
    )
    app.add_middleware(Boundary, token=token)

    @app.get("/healthz")
    def health():
        available = engine.is_file() and all((models / v).is_file() for v in MODELS.values())
        return JSONResponse(
            {"status": "ok" if available else "not_ready"}, status_code=200 if available else 503
        )

    @app.get("/v1/models")
    async def model_list():
        return {
            "object": "list",
            "data": [
                {"id": name, "object": "model", "owned_by": "local"} for name in ("auto", *MODELS)
            ],
        }

    @app.post("/v1/audio/transcriptions")
    @app.post("/inference", include_in_schema=False)
    async def transcribe(
        request: Request,
        file: Annotated[UploadFile, File()],
        model: Annotated[str, Form()] = "auto",
        language: Annotated[str, Form()] = "auto",
        response_format: Annotated[str, Form()] = "json",
        temperature: Annotated[float, Form()] = 0,
    ):
        nonlocal active
        model = ALIASES.get(model, model)
        language = {"iw": "he", "Hebrew": "he", "English": "en"}.get(language, language)
        if model not in ("auto", *MODELS):
            raise HTTPException(400, "Unknown model; see /v1/models")
        if language not in ("auto", "he", "en"):
            raise HTTPException(400, "Only auto, he and en are supported")
        if response_format not in ("json", "verbose_json", "text"):
            raise HTTPException(400, "Use json, verbose_json or text")
        if not math.isfinite(temperature) or temperature != 0:
            raise HTTPException(400, "This low-resource server uses temperature=0")
        async with gate:
            if active >= 2:
                raise HTTPException(429, "Busy; retry later", headers={"Retry-After": "10"})
            active += 1
        try:
            async with slots:
                if await request.is_disconnected():
                    raise HTTPException(499, "Client disconnected")
                with tempfile.TemporaryDirectory(prefix="audio-", dir=tmp) as directory:
                    work = Path(directory)
                    source, wav = work / "upload.bin", work / "audio.wav"
                    raw = await file.read(MAX_UPLOAD + 1)
                    if not raw or len(raw) > MAX_UPLOAD:
                        raise HTTPException(413, "Empty upload or upload exceeds 25 MiB")
                    if not sniff(raw[:16]):
                        raise HTTPException(415, "Unsupported audio container")
                    source.write_bytes(raw)
                    del raw
                    # Protocol allowlist prevents playlists and remote fetches; bound decoded
                    # duration, threads and output. User filenames are never passed to tools.
                    await command(
                        config["ffmpeg"],
                        "-nostdin",
                        "-y",
                        "-loglevel",
                        "error",
                        "-threads",
                        "2",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-i",
                        str(source),
                        "-t",
                        str(MAX_SECONDS + 1),
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        "-c:a",
                        "pcm_s16le",
                        "-threads",
                        "2",
                        str(wav),
                    )
                    out, _ = await command(
                        config["ffprobe"],
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "json",
                        str(wav),
                    )
                    duration = float(json.loads(out)["format"]["duration"])
                    if not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS:
                        raise HTTPException(413, "Audio exceeds the 5-minute limit")

                    async def infer(selected: str, lang: str):
                        prefix = work / "result"
                        await command(
                            str(engine),
                            "-m",
                            str(models / MODELS[selected]),
                            "-f",
                            str(wav),
                            "-l",
                            lang,
                            "-t",
                            "2",
                            "-p",
                            "1",
                            "-bs",
                            "5",
                            "-bo",
                            "5",
                            "-tp",
                            "0",
                            "-sns",
                            "-oj",
                            "-of",
                            str(prefix),
                            "-np",
                            deadline_seconds=300,
                        )
                        return parse_result(json.loads(prefix.with_suffix(".json").read_text()))

                    selected = model
                    if model == "auto":
                        selected = "ivrit-large-v3" if language == "he" else "large-v3-turbo"
                    if selected == "ivrit-large-v3" and language == "en":
                        raise HTTPException(400, "Use the turbo model for English")
                    text, detected, segments = await infer(selected, language)
                    # Unknown language: multilingual turbo first; re-check Hebrew with ivrit.
                    # Explicit language/model avoids that extra pass and costs less compute.
                    if model == "auto" and language == "auto" and detected == "he":
                        selected = "ivrit-large-v3"
                        text, detected, segments = await infer(selected, "he")
                    if detected not in ("he", "en"):
                        raise HTTPException(422, "Unsupported detected language; review required")
                    if response_format == "text":
                        return PlainTextResponse(text)
                    result = {
                        "text": text,
                        "language": detected,
                        "duration": duration,
                        "model": selected,
                    }
                    if response_format == "verbose_json":
                        result["segments"] = [
                            {
                                "id": i,
                                "text": s["text"],
                                "start": s["offsets"]["from"] / 1000,
                                "end": s["offsets"]["to"] / 1000,
                            }
                            for i, s in enumerate(segments)
                        ]
                    return result
        except HTTPException:
            raise
        except TimeoutError:
            raise HTTPException(504, "Local transcription timed out; review required") from None
        except (RuntimeError, ValueError, KeyError, TypeError, OSError):
            raise HTTPException(422, "Local transcription failed; review required") from None
        finally:
            await file.close()
            async with gate:
                active -= 1

    return app


if __name__ == "__main__":
    os.umask(0o077)
    config_path = Path(os.environ["MILA_API_CONFIG"])
    cfg = json.loads(config_path.read_text())
    # Python owns bounded log files; launchd redirects bootstrap output separately.
    logs = Path(cfg["data_dir"]) / "logs"
    logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(message)s"}},
        "handlers": {
            "rotating": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(logs / "api.log"),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
                "formatter": "plain",
            }
        },
        "root": {"handlers": ["rotating"], "level": "INFO"},
        "loggers": {
            "uvicorn": {"handlers": ["rotating"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": [], "propagate": False},
        },
    }
    uvicorn.run(
        create_app(cfg),
        log_config=log_config,
        host=cfg["host"],
        port=cfg["port"],
        workers=1,
        access_log=False,
        limit_concurrency=8,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=5,
    )
