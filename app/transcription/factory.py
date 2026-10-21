"""Pick the transcriber from the current settings at call time (no restart needed)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.jobs.queue import PermanentError
from app.settings_store import get_secret, get_setting
from app.transcription.base import Transcriber
from app.transcription.cloudflare import CloudflareTranscriber
from app.transcription.openai import OpenAITranscriber
from app.transcription.whisper import WhisperTranscriber


async def build_transcriber(db: AsyncSession, key_bytes: bytes) -> Transcriber:
    cfg = get_settings()
    provider = cfg.transcription_provider or (
        "local_whisper" if cfg.whisper_url else await get_setting(db, "transcription.provider")
    )
    if provider == "local_whisper":
        if not cfg.whisper_url:
            raise PermanentError("Local transcription endpoint is not configured")
        return WhisperTranscriber(
            cfg.whisper_url, cfg.whisper_api_key, cfg.whisper_model, cfg.whisper_fallback_model
        )
    if cfg.classification_provider == "ollama" and cfg.transcription_provider is None:
        raise PermanentError("Local transcription endpoint is not configured")
    if provider == "cloudflare":
        account = await get_setting(db, "transcription.cloudflare_account_id")
        token = await get_secret(db, "transcription.cloudflare_api_token", key_bytes)
        if not account or not token:
            raise PermanentError("Cloudflare transcription is not configured")
        return CloudflareTranscriber(
            account, token, str(await get_setting(db, "transcription.cloudflare_model"))
        )
    api_key = await get_secret(db, "openai.api_key", key_bytes)
    if not api_key:
        raise PermanentError("OpenAI API key is not configured")
    return OpenAITranscriber(api_key, str(await get_setting(db, "transcription.openai_model")))
