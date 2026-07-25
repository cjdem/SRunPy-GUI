"""Application version shared by Python and Windows build metadata."""

from typing import Final

PROGRAM_VERSION: Final[tuple[int, int, int, int]] = (1, 0, 9, 1)
__version__: Final[str] = ".".join(str(version_part) for version_part in PROGRAM_VERSION)
