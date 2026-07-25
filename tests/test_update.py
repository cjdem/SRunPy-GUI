import pytest

from srunpy.update import is_newer_release, normalize_release_version


def test_semantic_version_comparison_handles_double_digit_components() -> None:
    assert is_newer_release("v1.0.10", "1.0.9.1") is True
    assert is_newer_release("v1.0.9", "1.0.9.1") is False


def test_release_tag_does_not_require_v_prefix() -> None:
    assert is_newer_release("2.0.0", "1.9.9") is True


def test_invalid_release_tag_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_release_version("latest-build")
