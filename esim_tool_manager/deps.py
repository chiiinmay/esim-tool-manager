"""esim_tool_manager.deps
~~~~~~~~~~~~~~~~~~~~~~~
Dependency checker module. Checks Python version, pip availability,
eSim tool dependencies, and pip packages without invoking pip subprocesses
for querying package versions (uses importlib.metadata).
"""

from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal

from packaging.version import InvalidVersion, Version

from esim_tool_manager.versioning import compare, get_installed_version

if TYPE_CHECKING:
    from esim_tool_manager.backends.base import Backend
    from esim_tool_manager.config import Registry


class DepStatus(str, Enum):
    """Status of an individual dependency item."""

    OK = "ok"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class DepItem:
    """A single evaluated dependency item."""

    name: str
    kind: Literal["tool", "pip", "python", "pip_tool"]
    status: DepStatus
    found: str | None
    required: str | None
    fix: str | None


@dataclass(frozen=True)
class DepReport:
    """Report collecting all checked dependencies."""

    items: list[DepItem]

    @property
    def all_ok(self) -> bool:
        """Return True if all dependencies are satisfied."""
        return all(item.status == DepStatus.OK for item in self.items)

    @property
    def missing(self) -> list[DepItem]:
        """Return list of missing dependencies."""
        return [item for item in self.items if item.status == DepStatus.MISSING]

    @property
    def incompatible(self) -> list[DepItem]:
        """Return list of incompatible dependencies."""
        return [item for item in self.items if item.status == DepStatus.INCOMPATIBLE]


def _build_tool_fix(name: str, pkg_name: str, backend_name: str, version: str | None = None) -> str:
    """Build fix command for a system tool."""
    if backend_name == "apt":
        target = f"{pkg_name}={version}" if version else pkg_name
        return f"sudo apt-get install -y {target}"
    if backend_name == "winget":
        ver_flag = f" --version {version}" if version else ""
        return f"winget install --id {pkg_name} --exact --accept-package-agreements --accept-source-agreements{ver_flag}"
    return f"esim-tm install {name}"


def _build_pip_fix(pkg_name: str, apt_pkg: str | None = None) -> str:
    """Build fix command for a pip dependency, honoring PEP 668."""
    # PEP 668: on Debian/Ubuntu 23.04+ direct pip install fails with
    # externally-managed-environment. Prefer apt package when available.
    if apt_pkg:
        return f"sudo apt-get install -y {apt_pkg}"
    return f"python3 -m venv .venv && source .venv/bin/activate && pip install {pkg_name}"


def check_dependencies(registry: Registry, backend: Backend) -> DepReport:
    """Check all dependencies: Python runtime, pip capability, tools, and pip packages."""
    items: list[DepItem] = []

    # 1. Check Python version >= 3.8
    py_ver = sys.version_info
    major, minor, micro = py_ver[0], py_ver[1], py_ver[2]
    found_py = f"{major}.{minor}.{micro}"
    if (major, minor) < (3, 8):
        items.append(
            DepItem(
                name="python",
                kind="python",
                status=DepStatus.INCOMPATIBLE,
                found=found_py,
                required=">=3.8.0",
                fix="Install Python 3.8 or higher.",
            )
        )
    else:
        items.append(
            DepItem(
                name="python",
                kind="python",
                status=DepStatus.OK,
                found=found_py,
                required=">=3.8.0",
                fix=None,
            )
        )

    # 2. Check python3 -m pip works
    pip_ok = False
    found_pip_str: str | None = None
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            pip_ok = True
            found_pip_str = proc.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pip_ok = False

    if pip_ok:
        items.append(
            DepItem(
                name="pip",
                kind="pip_tool",
                status=DepStatus.OK,
                found=found_pip_str,
                required="available",
                fix=None,
            )
        )
    else:
        pip_fix = (
            "sudo apt-get install -y python3-pip"
            if backend.name == "apt"
            else f"{sys.executable} -m ensurepip --upgrade"
        )
        items.append(
            DepItem(
                name="pip",
                kind="pip_tool",
                status=DepStatus.MISSING,
                found=None,
                required="available",
                fix=pip_fix,
            )
        )

    # 3. Check tools and their depends_on
    for tool in registry.all_tools():
        pkg_name = tool.pkg_name_for(backend.name) or tool.pip_package

        if tool.kind == "pip":
            # Check pip package via importlib.metadata
            try:
                dist_ver_str = importlib.metadata.version(tool.pip_package)
                dist_ver = Version(dist_ver_str)
                is_below = False
                if tool.min_version:
                    if compare(dist_ver, tool.min_version) == "below_minimum":
                        is_below = True

                if is_below:
                    items.append(
                        DepItem(
                            name=tool.name,
                            kind="pip",
                            status=DepStatus.INCOMPATIBLE,
                            found=dist_ver_str,
                            required=f">={tool.min_version}",
                            fix=_build_pip_fix(tool.pip_package, tool.pkg_name_apt or None),
                        )
                    )
                else:
                    items.append(
                        DepItem(
                            name=tool.name,
                            kind="pip",
                            status=DepStatus.OK,
                            found=dist_ver_str,
                            required=f">={tool.min_version}" if tool.min_version else None,
                            fix=None,
                        )
                    )
            except importlib.metadata.PackageNotFoundError:
                items.append(
                    DepItem(
                        name=tool.name,
                        kind="pip",
                        status=DepStatus.MISSING,
                        found=None,
                        required=f">={tool.min_version}" if tool.min_version else None,
                        fix=_build_pip_fix(tool.pip_package, tool.pkg_name_apt or None),
                    )
                )
        else:
            # System tool
            res = get_installed_version(tool)
            if res.status == "not_installed":
                fix_cmd = _build_tool_fix(tool.name, pkg_name, backend.name, tool.min_version or None)
                items.append(
                    DepItem(
                        name=tool.name,
                        kind="tool",
                        status=DepStatus.MISSING,
                        found=None,
                        required=f">={tool.min_version}" if tool.min_version else None,
                        fix=fix_cmd,
                    )
                )
            elif res.status in ("unparsable", "timeout") or res.version is None:
                fix_cmd = _build_tool_fix(tool.name, pkg_name, backend.name)
                items.append(
                    DepItem(
                        name=tool.name,
                        kind="tool",
                        status=DepStatus.INCOMPATIBLE,
                        found=res.status,
                        required=f">={tool.min_version}" if tool.min_version else None,
                        fix=fix_cmd,
                    )
                )
            else:
                is_below = False
                if tool.min_version:
                    if compare(res.version, tool.min_version) == "below_minimum":
                        is_below = True

                if is_below:
                    fix_cmd = _build_tool_fix(tool.name, pkg_name, backend.name, tool.min_version)
                    items.append(
                        DepItem(
                            name=tool.name,
                            kind="tool",
                            status=DepStatus.INCOMPATIBLE,
                            found=str(res.version),
                            required=f">={tool.min_version}",
                            fix=fix_cmd,
                        )
                    )
                else:
                    items.append(
                        DepItem(
                            name=tool.name,
                            kind="tool",
                            status=DepStatus.OK,
                            found=str(res.version),
                            required=f">={tool.min_version}" if tool.min_version else None,
                            fix=None,
                        )
                    )

    return DepReport(items=items)
