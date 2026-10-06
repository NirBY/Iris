"""Shared provider clients, rebuilt when the configured credentials change."""

from app.classify.moderation import ModerationClient


class Providers:
    def __init__(self) -> None:
        self._moderation: tuple[str, ModerationClient] | None = None

    def moderation(self, api_key: str) -> ModerationClient:
        if self._moderation is None or self._moderation[0] != api_key:
            self._moderation = (api_key, ModerationClient(api_key))
        return self._moderation[1]

    async def aclose(self) -> None:
        if self._moderation is not None:
            await self._moderation[1].aclose()
            self._moderation = None
