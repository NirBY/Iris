import pytest

from scripts.release_version import release_version


@pytest.mark.parametrize("tag", ["2026.10.0", "v2026.10.12", "2026.1.0"])
def test_stable_release(tag):
    assert release_version(tag) == {
        "tag": tag,
        "version": tag.removeprefix("v"),
        "prerelease": "false",
    }


@pytest.mark.parametrize("stage", ["alpha", "beta", "rc"])
def test_prerelease(stage):
    assert release_version(f"v2026.10.0-{stage}.56")["prerelease"] == "true"


@pytest.mark.parametrize(
    "tag",
    ["latest", "2026.13.0", "2026.0.1", "2026.10.01", "2026.10.0-beta.0", "2026.10.0\nX=1"],
)
def test_invalid_release(tag):
    with pytest.raises(ValueError):
        release_version(tag)
