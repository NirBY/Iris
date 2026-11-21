"""WhatsApp animated stickers (`application/was`): a ZIP holding a Lottie JSON animation.

Only the animation JSON is read, with bounded sizes, and nothing is extracted to disk.
Image assets that point at files or URLs are dropped so a viewer never fetches anything;
inline (data:) images are kept. Expressions are left in the data but the viewer uses
lottie-web's light build, which has no expression engine.
"""

import json
import zipfile
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_RATIO = 200  # compressed-to-expanded bound against ZIP bombs
_NAMES = ("animation/animation.json", "animation.json")


class NotLottie(ValueError):
    pass


def is_lottie_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return any(name in archive.NameToInfo for name in _NAMES)
    except (zipfile.BadZipFile, OSError):
        return False


def _safe_assets(assets: Any) -> list[Any]:
    kept = []
    for asset in assets if isinstance(assets, list) else []:
        if not isinstance(asset, dict):
            continue
        path = asset.get("p")
        if isinstance(path, str) and path and not path.startswith("data:image/"):
            continue  # external file/URL image; never fetched by the viewer
        kept.append(asset)
    return kept


def read_animation(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            info = next((archive.NameToInfo[n] for n in _NAMES if n in archive.NameToInfo), None)
            if info is None:
                raise NotLottie("no animation in sticker")
            if info.file_size > MAX_JSON_BYTES or info.file_size > MAX_RATIO * max(
                info.compress_size, 1
            ):
                raise NotLottie("animation is too large")
            with archive.open(info) as fh:
                raw = fh.read(MAX_JSON_BYTES + 1)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise NotLottie("sticker archive is unreadable") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise NotLottie("animation is too large")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise NotLottie("animation is not valid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("layers"), list):
        raise NotLottie("not a Lottie animation")
    data["assets"] = _safe_assets(data.get("assets"))
    return data
