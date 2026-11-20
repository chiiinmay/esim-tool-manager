"""esim_tool_manager.backends.base
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Base classes, Result dataclass, and shared execution helpers for package
manager backends.
"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

ErrorKind = Literal[
    "permission",
    "network",
    "not_found",
    "version_unavailable",
    "unknown",
]


@dataclass(frozen=True)
class Result:
    """Result of a backend execution (install, upgrade, refresh)."""

    success: bool
    message: str
    command: list[str]
    dry_run: bool
    error_kind: ErrorKind | None = None


def classify_error(stderr: str) -> ErrorKind:
    """Map common package-manager error messages to a structured ErrorKind."""
    lowered = stderr.lower()

    if any(p in lowered for p in [
        "permission denied",
        "are you root",
        "need to be root",
        "requires admin",
        "access is denied",
        "failed to lock",
        "could not open lock file",
    ]):
        return "permission"

    if any(p in lowered for p in [
        "could not resolve",
        "failed to connect",
        "connection timed out",
        "network is unreachable",
        "temporary failure in name resolution",
        "failed to fetch",
        "0x80072ee7",
    ]):
        return "network"

    if any(p in lowered for p in [
        "unable to locate package",
        "no package found",
        "no applicable update found",
        "cannot find",
        "not found",
    ]):
        return "not_found"

    if any(p in lowered for p in [
        "version ... was not found",
        "version was not found",
        "no matching version",
        "requested version not found",
        "cannot find version",
    ]):
        return "version_unavailable"

    return "unknown"


def _run(
    cmd: list[str],
    dry_run: bool = False,
    timeout: int = 300,
    env: dict[str, str] | None = None,
) -> Result:
    """Run a subprocess command safely with a timeout and return a Result.

    In dry-run mode, this does NOT execute anything and simply returns a
    success Result containing the would-be command.
    """
    if dry_run:
        return Result(
            success=True,
            message=f"Dry run: would execute {' '.join(cmd)}",
            command=cmd,
            dry_run=True,
            error_kind=None,
        )

    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=full_env,
        )
    except FileNotFoundError as exc:
        return Result(
            success=False,
            message=f"Command not found: {cmd[0]} ({exc})",
            command=cmd,
            dry_run=False,
            error_kind="not_found",
        )
    except subprocess.TimeoutExpired:
        return Result(
            success=False,
            message=f"Command timed out after {timeout} seconds: {' '.join(cmd)}",
            command=cmd,
            dry_run=False,
            error_kind="unknown",
        )

    if proc.returncode == 0:
        return Result(
            success=True,
            message=proc.stdout.strip(),
            command=cmd,
            dry_run=False,
            error_kind=None,
        )

    combined_err = (proc.stderr + "\n" + proc.stdout).strip()
    kind = classify_error(combined_err)
    return Result(
        success=False,
        message=combined_err,
        command=cmd,
        dry_run=False,
        error_kind=kind,
    )


class Backend(ABC):
    """Abstract base class for package manager backends."""

    name: str

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend tool is available on the current host."""

    @abstractmethod
    def candidate_version(self, pkg: str) -> str | None:
        """Return the candidate version available to install, or None."""

    @abstractmethod
    def install(
        self,
        pkg: str,
        version: str | None = None,
        dry_run: bool = False,
    ) -> Result:
        """Install *pkg*, optionally pinned to *version*."""

    @abstractmethod
    def upgrade(self, pkg: str, dry_run: bool = False) -> Result:
        """Upgrade *pkg* to the latest available candidate."""
