"""Validate release tags before any publishing credentials are used."""

import re
import sys


def release_version(tag: str) -> dict[str, str]:
    match = re.fullmatch(
        r"v?([0-9]{4}\.(?:0?[1-9]|1[0-2])\.(?:0|[1-9][0-9]*)(?:-(?:alpha|beta|rc)\.[1-9][0-9]*)?)",
        tag,
    )
    if not match:
        raise ValueError("Expected YYYY.M.PATCH or YYYY.M.PATCH-beta.N (alpha/rc also supported)")
    version = match.group(1)
    return {"tag": tag, "version": version, "prerelease": str("-" in version).lower()}


if __name__ == "__main__":
    for key, value in release_version(sys.argv[1]).items():
        print(f"{key}={value}")
