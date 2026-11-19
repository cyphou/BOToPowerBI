"""Helpers for creating new output files without following a final symlink."""

import os
from pathlib import Path
from typing import TextIO


def open_new_text(path: Path) -> TextIO:
    """Create a new UTF-8 text file without replacing an existing entry."""
    if os.name != "nt":
        return path.open("x", encoding="utf-8", newline="\n")

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    # Windows' CRT follows dangling symlinks even in mode "x".
    generic_write = 0x40000000
    share_read_write = 0x00000003
    create_new = 1
    attribute_normal = 0x00000080
    open_reparse_point = 0x00200000
    handle = create_file(
        os.fspath(path), generic_write, share_read_write, None, create_new,
        attribute_normal | open_reparse_point, None,
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.WinError(ctypes.get_last_error())
        error.filename = os.fspath(path)
        raise error

    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    except OSError:
        close_handle(handle)
        raise
    try:
        return os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
    except (OSError, ValueError):
        os.close(descriptor)
        raise
