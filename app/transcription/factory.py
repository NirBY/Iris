"""Pick the transcriber from the current settings at call time (no restart needed)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.queue import PermanentError
from app.settings_store import get_secret, get_setting
from app.transcription.base import Transcriber
from app.transcription.cloudflare import CloudflareTranscriber
from app.transcription.openai import OpenAITranscriber


async def build_transcriber(db: AsyncSession, key_bytes: bytes) -> Transcriber:
    provider = await get_setting(db, "transcription.provider")
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
