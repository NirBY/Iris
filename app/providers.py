"""Shared provider clients, rebuilt when the configured credentials change."""

from app.classify.moderation import ModerationClient


class Providers:
    def __init__(self) -> None:
        self._moderation: tuple[str, ModerationClient] | None = None
        self._retired: list[ModerationClient] = []  # may still serve in-flight requests

    def moderation(self, api_key: str) -> ModerationClient:
        if self._moderation is None or self._moderation[0] != api_key:
            if self._moderation is not None:
                self._retired.append(self._moderation[1])
            self._moderation = (api_key, ModerationClient(api_key))
        return self._moderation[1]

    async def aclose(self) -> None:
        for client in self._retired:
            await client.aclose()
        self._retired = []
        if self._moderation is not None:
            await self._moderation[1].aclose()
            self._moderation = None
