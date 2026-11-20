"""esim_tool_manager.backends
~~~~~~~~~~~~~~~~~~~~~~~~~~
Backend registry mapping platform backend names to backend classes.
Provides `get_backend()` factory function.
"""

from __future__ import annotations

from esim_tool_manager.backends.apt import AptBackend
from esim_tool_manager.backends.base import Backend, Result
from esim_tool_manager.backends.winget import WingetBackend
from esim_tool_manager.platform_detect import UnsupportedPlatformError, detect_backend

BACKENDS: dict[str, type[Backend]] = {
    "apt": AptBackend,
    "winget": WingetBackend,
}


def get_backend(name: str | None = None) -> Backend:
    """Return an instantiated backend.

    If *name* is None, uses :func:`platform_detect.detect_backend`.
    Raises :class:`UnsupportedPlatformError` if no supported backend is available.
    """
    selected = name if name is not None else detect_backend()
    if selected is None or selected not in BACKENDS:
        raise UnsupportedPlatformError(
            f"No supported backend available for '{selected}'. "
            "Supported backends are: " + ", ".join(BACKENDS.keys())
        )

    backend_cls = BACKENDS[selected]
    return backend_cls()


__all__ = ["BACKENDS", "Backend", "Result", "AptBackend", "WingetBackend", "get_backend"]
