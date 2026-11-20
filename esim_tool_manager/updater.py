"""esim_tool_manager.updater
~~~~~~~~~~~~~~~~~~~~~~~~~~
Logic for checking tool updates, comparing candidate vs installed versions,
and upgrading tools safely without downgrading or auto-installing missing tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version

from esim_tool_manager.backends.base import Result
from esim_tool_manager.versioning import compare, get_installed_version

if TYPE_CHECKING:
    from esim_tool_manager.backends.base import Backend
    from esim_tool_manager.config import Registry, ToolSpec


class UpdateStatus(str, Enum):
    """Status classification for tool update checks."""

    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    NOT_INSTALLED = "not_installed"
    BELOW_MINIMUM = "below_minimum"
    UNPARSABLE = "unparsable"
    UNKNOWN_CANDIDATE = "unknown_candidate"


@dataclass(frozen=True)
class UpdateRow:
    """Row in an update check report for a single tool."""

    name: str
    installed: Version | None
    candidate: str | None
    required: str | None
    status: UpdateStatus


def check_updates(registry: Registry, backend: Backend) -> list[UpdateRow]:
    """Check update status for all tools in *registry* against *backend*.

    BELOW_MINIMUM takes priority over UPDATE_AVAILABLE.
    """
    rows: list[UpdateRow] = []

    for tool in registry.all_tools():
        ver_res = get_installed_version(tool)
        required = tool.min_version if tool.min_version else None

        if ver_res.status == "not_installed":
            rows.append(
                UpdateRow(
                    name=tool.name,
                    installed=None,
                    candidate=None,
                    required=required,
                    status=UpdateStatus.NOT_INSTALLED,
                )
            )
            continue

        if ver_res.status in ("unparsable", "timeout"):
            rows.append(
                UpdateRow(
                    name=tool.name,
                    installed=None,
                    candidate=None,
                    required=required,
                    status=UpdateStatus.UNPARSABLE,
                )
            )
            continue

        installed_ver = ver_res.version
        assert installed_ver is not None

        # Check candidate version from backend
        pkg_name = tool.pkg_name_for(backend.name)
        cand_str = backend.candidate_version(pkg_name) if pkg_name else None

        # Check against minimum requirement
        is_below_min = False
        if tool.min_version:
            if compare(installed_ver, tool.min_version) == "below_minimum":
                is_below_min = True

        if is_below_min:
            rows.append(
                UpdateRow(
                    name=tool.name,
                    installed=installed_ver,
                    candidate=cand_str,
                    required=required,
                    status=UpdateStatus.BELOW_MINIMUM,
                )
            )
            continue

        if cand_str is None:
            rows.append(
                UpdateRow(
                    name=tool.name,
                    installed=installed_ver,
                    candidate=None,
                    required=required,
                    status=UpdateStatus.UNKNOWN_CANDIDATE,
                )
            )
            continue

        try:
            cand_ver = Version(cand_str)
        except InvalidVersion:
            rows.append(
                UpdateRow(
                    name=tool.name,
                    installed=installed_ver,
                    candidate=cand_str,
                    required=required,
                    status=UpdateStatus.UNKNOWN_CANDIDATE,
                )
            )
            continue

        if cand_ver > installed_ver:
            status = UpdateStatus.UPDATE_AVAILABLE
        else:
            status = UpdateStatus.UP_TO_DATE

        rows.append(
            UpdateRow(
                name=tool.name,
                installed=installed_ver,
                candidate=cand_str,
                required=required,
                status=status,
            )
        )

    return rows


def update(
    tool_name: str,
    registry: Registry,
    backend: Backend,
    dry_run: bool = False,
) -> Result:
    """Update a single tool.

    * Unknown tool name -> clear error
    * Not installed -> do NOT install; return Result instructing to run install
    * Already up to date -> success Result, run nothing
    * Downgrade prevention: if candidate < installed, do nothing
    * Otherwise call backend.upgrade
    """
    if tool_name not in registry:
        return Result(
            success=False,
            message=f"Unknown tool '{tool_name}'. Available: {', '.join(s.name for s in registry.all_tools())}",
            command=[],
            dry_run=dry_run,
            error_kind="not_found",
        )

    tool = registry.get(tool_name)
    ver_res = get_installed_version(tool)

    if ver_res.status == "not_installed":
        return Result(
            success=False,
            message=f"Tool '{tool_name}' is not installed. Run `esim-tm install {tool_name}` to install it.",
            command=[],
            dry_run=dry_run,
            error_kind="not_found",
        )

    if ver_res.status in ("unparsable", "timeout"):
        return Result(
            success=False,
            message=f"Cannot determine installed version for '{tool_name}' (status: {ver_res.status}).",
            command=[],
            dry_run=dry_run,
            error_kind="unknown",
        )

    installed_ver = ver_res.version
    assert installed_ver is not None

    pkg_name = tool.pkg_name_for(backend.name)
    if not pkg_name and tool.kind != "pip":
        return Result(
            success=False,
            message=f"Tool '{tool_name}' has no package defined for backend '{backend.name}'.",
            command=[],
            dry_run=dry_run,
            error_kind="not_found",
        )

    target_pkg = pkg_name or tool.pip_package
    cand_str = backend.candidate_version(target_pkg)

    if cand_str is None:
        return Result(
            success=False,
            message=(
                f"No candidate version found for '{tool_name}'. "
                "Consider refreshing package index (e.g. `apt-get update`)."
            ),
            command=[],
            dry_run=dry_run,
            error_kind="version_unavailable",
        )

    try:
        cand_ver = Version(cand_str)
    except InvalidVersion:
        return Result(
            success=False,
            message=f"Candidate version '{cand_str}' for '{tool_name}' is unparsable.",
            command=[],
            dry_run=dry_run,
            error_kind="version_unavailable",
        )

    if cand_ver == installed_ver:
        return Result(
            success=True,
            message=f"Tool '{tool_name}' is already up to date ({installed_ver}).",
            command=[],
            dry_run=dry_run,
            error_kind=None,
        )

    if cand_ver < installed_ver:
        return Result(
            success=True,
            message=(
                f"Candidate version ({cand_ver}) is older than installed version ({installed_ver}) "
                f"for '{tool_name}'. Will not downgrade."
            ),
            command=[],
            dry_run=dry_run,
            error_kind=None,
        )

    # Candidate is newer -> perform upgrade
    return backend.upgrade(target_pkg, dry_run=dry_run)


def update_all(
    registry: Registry,
    backend: Backend,
    dry_run: bool = False,
) -> list[Result]:
    """Update all tools in registry.

    Continues even if updating a tool fails.
    If no candidates are found across all tools, appends a hint to the results.
    """
    results: list[Result] = []
    all_candidates_none = True

    for tool in registry.all_tools():
        pkg = tool.pkg_name_for(backend.name) or tool.pip_package
        if pkg and backend.candidate_version(pkg) is not None:
            all_candidates_none = False

        res = update(tool.name, registry, backend, dry_run=dry_run)
        results.append(res)

    if all_candidates_none and results:
        hint_result = Result(
            success=False,
            message="Hint: Candidate versions were unavailable for all tools. Try refreshing package index first.",
            command=[],
            dry_run=dry_run,
            error_kind="version_unavailable",
        )
        results.append(hint_result)

    return results
