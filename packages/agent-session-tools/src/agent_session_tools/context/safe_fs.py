"""POSIX descriptor-anchored filesystem helpers for security boundaries."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from typing import Final

_REQUIRED_FLAGS: Final = ("O_DIRECTORY", "O_NOFOLLOW")
_DIRECTORY_OPEN_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_READ_FLAGS: Final = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)
_FILE_CREATE_FLAGS: Final = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _require_secure_open_flags() -> None:
    if any(not hasattr(os, name) for name in _REQUIRED_FLAGS):
        raise OSError(
            errno.ENOTSUP, "Secure descriptor-relative traversal is unavailable"
        )


def _open_directory_nofollow(path: Path) -> int:
    """Open every absolute path component relative to a pinned parent descriptor."""
    _require_secure_open_flags()
    absolute = Path(os.path.abspath(os.fspath(path)))
    if not absolute.is_absolute():
        raise OSError(
            errno.EINVAL, "Directory path must resolve lexically to an absolute path"
        )

    descriptor = os.open(os.sep, _DIRECTORY_OPEN_FLAGS)
    try:
        for component in absolute.parts[1:]:
            if component in ("", ".", ".."):
                raise OSError(errno.EINVAL, "Unsafe directory component")
            child = os.open(
                component,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(errno.ENOTDIR, "Path is not a directory")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise
