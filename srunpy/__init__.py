"""
SRunPy - Third-party Srun Gateway Authentication Client
深澜网关第三方认证客户端

This package provides functionality to authenticate with Srun gateway systems.
本包提供深澜网关系统的认证功能。
"""

from .html import WebRoot
from .srun import Srun_Py as SrunClient
from .version import PROGRAM_VERSION, __version__

__all__ = ["PROGRAM_VERSION", "SrunClient", "WebRoot", "__version__"]
