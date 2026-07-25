"""Safe Windows single-instance coordination."""

import ctypes
from ctypes import wintypes


class WindowsSingleInstance:
    """Own a named Windows mutex for the lifetime of the application."""

    _ERROR_ALREADY_EXISTS = 183

    def __init__(self, mutex_name: str = "Local\\SRunPy.Desktop") -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not self._handle:
            raise ctypes.WinError()
        self.is_already_running = kernel32.GetLastError() == self._ERROR_ALREADY_EXISTS

    def close(self) -> None:
        """Release the process handle; Windows releases mutex ownership on exit."""
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "WindowsSingleInstance":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
