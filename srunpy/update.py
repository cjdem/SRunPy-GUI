"""Version parsing helpers for update checks."""

from packaging.version import InvalidVersion, Version


def normalize_release_version(release_tag: str) -> Version:
    """Parse a GitHub release tag without assuming that it starts with ``v``."""
    normalized_tag = release_tag.strip()
    if normalized_tag.lower().startswith("v"):
        normalized_tag = normalized_tag[1:]
    try:
        return Version(normalized_tag)
    except InvalidVersion as error:
        raise ValueError(f"无效的版本号：{release_tag}") from error


def is_newer_release(release_tag: str, current_version: str) -> bool:
    """Return whether a release tag is newer than the installed version."""
    return normalize_release_version(release_tag) > normalize_release_version(current_version)
