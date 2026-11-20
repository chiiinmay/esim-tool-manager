"""esim_tool_manager.platform_detect
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Detects the current operating system, Linux distro, available package
manager backend, and privilege level.

Public API
----------
- detect_os()          -> "linux" | "windows" | "macos"
- detect_distro()      -> DistroInfo | None
- detect_backend()     -> "apt" | "winget" | None
- is_privileged()      -> bool
- get_platform_info()  -> PlatformInfo
- UnsupportedPlatformError

The ``_os_release`` parameter on :func:`detect_distro` is a private seam
for unit-testing without touching the real filesystem.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ``os.geteuid`` only exists on POSIX (Linux/macOS). We bind it at module
# level so unit tests can patch ``esim_tool_manager.platform_detect.geteuid``
# regardless of the host OS the tests run on.
if hasattr(os, "geteuid"):
    geteuid = os.geteuid
else:
    def geteuid() -> int:  # type: ignore[misc]
        """Stub for Windows — always returns a non-root UID."""
        return 65534


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class UnsupportedPlatformError(RuntimeError):
    """Raised by :func:`get_platform_info` when no backend is available."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DistroInfo:
    """Parsed fields from ``/etc/os-release``."""

    id: str           # e.g. "ubuntu", "debian", "linuxmint"
    version_id: str   # e.g. "22.04", "12"


@dataclass(frozen=True)
class PlatformInfo:
    """Snapshot of everything the tool manager needs to know about this host."""

    os: Literal["linux", "windows", "macos"]
    distro: DistroInfo | None   # Linux only; None on other OSes or missing file
    backend: str | None         # "apt" | "winget" | None
    privileged: bool            # True if the process can install packages


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def detect_os() -> Literal["linux", "windows", "macos"]:
    """Return a normalised OS identifier.

    Uses :func:`platform.system`.  Any value other than ``"Linux"`` or
    ``"Windows"`` is mapped to ``"macos"`` for the common Darwin case; truly
    unknown OSes will simply get ``"macos"`` and subsequently fail backend
    detection, which is the correct behaviour.
    """
    system = platform.system()
    if system == "Linux":
        return "linux"
    if system == "Windows":
        return "windows"
    return "macos"


def detect_distro(
    *,
    _os_release: Path | None = None,
) -> DistroInfo | None:
    """Parse ``/etc/os-release`` and return a :class:`DistroInfo`.

    Returns ``None`` on non-Linux platforms or if the file is missing.

    Parameters
    ----------
    _os_release:
        Override the path to ``os-release``; intended for unit tests only.
    """
    if detect_os() != "linux":
        return None

    path = _os_release if _os_release is not None else Path("/etc/os-release")
    if not path.exists():
        return None

    data: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            # Strip surrounding quotes that os-release uses for some fields
            data[key.strip()] = val.strip().strip('"').strip("'")

    return DistroInfo(
        id=data.get("ID", ""),
        version_id=data.get("VERSION_ID", ""),
    )


def detect_backend() -> Literal["apt", "winget"] | None:
    """Return the package manager backend available on this host.

    - Linux   → checks for ``apt-get`` via :func:`shutil.which`
    - Windows → checks for ``winget``
    - Other   → ``None``
    """
    os_name = detect_os()
    if os_name == "linux":
        return "apt" if shutil.which("apt-get") else None
    if os_name == "windows":
        return "winget" if shutil.which("winget") else None
    return None


def is_privileged() -> bool:
    """Return ``True`` if the current process can install system packages.

    - Linux: ``True`` if running as root (UID 0) **or** ``sudo`` is on PATH.
    - Windows: ``True`` if the process has administrator privileges
      (checked via ``ctypes.windll.shell32.IsUserAnAdmin``).
    - Other OS: ``False``.
    """
    os_name = detect_os()

    if os_name == "linux":
        # ``geteuid`` is the module-level alias that tests can patch.
        if geteuid() == 0:
            return True
        return shutil.which("sudo") is not None

    if os_name == "windows":
        try:
            import ctypes  # noqa: PLC0415 — import inside function is intentional
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            return False

    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_platform_info() -> PlatformInfo:
    """Return a fully populated :class:`PlatformInfo` for the current host.

    Raises
    ------
    UnsupportedPlatformError
        When no supported backend (``apt-get`` / ``winget``) is detected,
        with a human-friendly explanation of what is missing.
    """
    os_name = detect_os()
    backend = detect_backend()

    if backend is None:
        if os_name == "linux":
            msg = (
                "apt-get not found; this tool supports Debian/Ubuntu Linux. "
                "Make sure apt is installed and on PATH, or use a supported "
                "distribution (Debian, Ubuntu, Linux Mint, etc.)."
            )
        elif os_name == "windows":
            msg = (
                "winget not found; this tool requires Windows Package Manager. "
                "Install 'App Installer' from the Microsoft Store to get winget."
            )
        else:
            msg = (
                f"Unsupported OS: {os_name!r}. "
                "esim-tm supports Debian/Ubuntu Linux (apt) and Windows (winget)."
            )
        raise UnsupportedPlatformError(msg)

    return PlatformInfo(
        os=os_name,
        distro=detect_distro(),
        backend=backend,
        privileged=is_privileged(),
    )
