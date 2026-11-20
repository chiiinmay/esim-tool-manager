"""esim_tool_manager.backends.apt
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Apt/apt-get package manager backend for Debian/Ubuntu systems.
Primary backend, fully tested with mocked subprocess calls.
"""

from __future__ import annotations

import re
import shutil
import subprocess

from esim_tool_manager.backends.base import Backend, Result, _run
from esim_tool_manager.platform_detect import geteuid
from esim_tool_manager.versioning import normalize_version

_CANDIDATE_REGEX = re.compile(r"Candidate:\s*([^\s\n]+)")


class AptBackend(Backend):
    """Wrapper for apt-get and apt-cache on Debian/Ubuntu."""

    name = "apt"

    def is_available(self) -> bool:
        """Check if apt-get is available on PATH."""
        return shutil.which("apt-get") is not None

    def _prepare_cmd(self, subcmd_and_args: list[str]) -> tuple[list[str] | None, Result | None]:
        """Prepare command with sudo if needed.

        Returns (cmd_list, None) or (None, failure_result).
        """
        is_root = geteuid() == 0
        has_sudo = shutil.which("sudo") is not None

        if is_root:
            return ["apt-get"] + subcmd_and_args, None

        if has_sudo:
            return ["sudo", "apt-get"] + subcmd_and_args, None

        return None, Result(
            success=False,
            message="Installing via apt requires root privileges, but current user is not root and sudo was not found on PATH.",
            command=["apt-get"] + subcmd_and_args,
            dry_run=False,
            error_kind="permission",
        )

    def refresh_index(self, dry_run: bool = False) -> Result:
        """Run `apt-get update` to refresh the package cache."""
        cmd, perm_err = self._prepare_cmd(["update"])
        if perm_err:
            return perm_err
        assert cmd is not None
        return _run(cmd, dry_run=dry_run, env={"DEBIAN_FRONTEND": "noninteractive"})

    def candidate_version(self, pkg: str) -> str | None:
        """Parse `apt-cache policy <pkg>` for the Candidate line."""
        try:
            proc = subprocess.run(
                ["apt-cache", "policy", pkg],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        if proc.returncode != 0:
            return None

        match = _CANDIDATE_REGEX.search(proc.stdout)
        if not match:
            return None

        cand = match.group(1).strip()
        if cand == "(none)":
            return None

        return normalize_version(cand)

    def install(
        self,
        pkg: str,
        version: str | None = None,
        dry_run: bool = False,
    ) -> Result:
        """Install *pkg*, optionally pinned with ``pkg=version``."""
        target = f"{pkg}={version}" if version else pkg
        cmd, perm_err = self._prepare_cmd(["install", "-y", target])
        if perm_err:
            return perm_err
        assert cmd is not None
        return _run(cmd, dry_run=dry_run, env={"DEBIAN_FRONTEND": "noninteractive"})

    def upgrade(self, pkg: str, dry_run: bool = False) -> Result:
        """Upgrade *pkg* using `--only-upgrade`."""
        cmd, perm_err = self._prepare_cmd(["install", "-y", "--only-upgrade", pkg])
        if perm_err:
            return perm_err
        assert cmd is not None
        return _run(cmd, dry_run=dry_run, env={"DEBIAN_FRONTEND": "noninteractive"})
