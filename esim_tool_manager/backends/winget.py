"""esim_tool_manager.backends.winget
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Winget backend — wraps winget for Windows systems.

NOTE: Untested on real Windows.
Covered by mocked tests only. See README and DESIGN.md for details.
"""

from __future__ import annotations

import re
import shutil
import subprocess

from esim_tool_manager.backends.base import Backend, Result, _run
from esim_tool_manager.versioning import normalize_version

_VERSION_LINE_REGEX = re.compile(r"Version:\s*([^\s\n]+)", re.IGNORECASE)


class WingetBackend(Backend):
    """Wrapper for the Windows Package Manager (winget). Untested on real Windows."""

    name = "winget"

    def is_available(self) -> bool:
        """Check if winget is available on PATH."""
        return shutil.which("winget") is not None

    def candidate_version(self, pkg: str) -> str | None:
        """Parse `winget show --id <pkg> --exact` for Version line."""
        try:
            proc = subprocess.run(
                ["winget", "show", "--id", pkg, "--exact"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        if proc.returncode != 0:
            return None

        match = _VERSION_LINE_REGEX.search(proc.stdout)
        if not match:
            return None

        cand = match.group(1).strip()
        return normalize_version(cand)

    def install(
        self,
        pkg: str,
        version: str | None = None,
        dry_run: bool = False,
    ) -> Result:
        """Install *pkg* using winget."""
        cmd = [
            "winget",
            "install",
            "--id",
            pkg,
            "--exact",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
        if version:
            cmd.extend(["--version", version])

        return _run(cmd, dry_run=dry_run)

    def upgrade(self, pkg: str, dry_run: bool = False) -> Result:
        """Upgrade *pkg* using winget."""
        cmd = [
            "winget",
            "upgrade",
            "--id",
            pkg,
            "--exact",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
        return _run(cmd, dry_run=dry_run)
