"""esim_tool_manager.cli
~~~~~~~~~~~~~~~~~~~~~
CLI interface for the eSim Tool Manager using argparse only.
No business logic: delegates directly to config, backends, updater, deps, and logger.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import Sequence

from esim_tool_manager import __version__
from esim_tool_manager.backends import get_backend
from esim_tool_manager.config import ConfigError, load_registry
from esim_tool_manager.deps import DepStatus, check_dependencies
from esim_tool_manager.logger import log_action, read_log
from esim_tool_manager.platform_detect import UnsupportedPlatformError
from esim_tool_manager.updater import UpdateStatus, check_updates, update, update_all


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format tabular data with left-aligned columns padded to content length."""
    num_cols = len(headers)
    widths = [len(h) for h in headers]

    for row in rows:
        for idx in range(num_cols):
            val = row[idx] if idx < len(row) else ""
            if len(val) > widths[idx]:
                widths[idx] = len(val)

    header_line = "  ".join(headers[i].ljust(widths[i]) for i in range(num_cols))
    sep_line = "  ".join("-" * widths[i] for i in range(num_cols))

    body_lines = [
        "  ".join((row[i] if i < len(row) else "").ljust(widths[i]) for i in range(num_cols))
        for row in rows
    ]

    return "\n".join([header_line, sep_line] + body_lines)


def cmd_list(args: argparse.Namespace) -> int:
    """Handle `list` subcommand: print status table for all registered tools."""
    backend = get_backend()
    registry = load_registry(backend=backend.name)
    rows_data = check_updates(registry, backend)

    table_rows = []
    for r in rows_data:
        table_rows.append([
            r.name,
            str(r.installed) if r.installed else "-",
            r.candidate or "-",
            r.required or "-",
            r.status.value,
        ])

    print(_format_table(["Tool", "Installed", "Candidate", "Required", "Status"], table_rows))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Handle `check` subcommand: print status table; exit 1 if anything is not UP_TO_DATE."""
    backend = get_backend()
    registry = load_registry(backend=backend.name)
    rows_data = check_updates(registry, backend)

    table_rows = []
    all_up_to_date = True
    for r in rows_data:
        if r.status != UpdateStatus.UP_TO_DATE:
            all_up_to_date = False
        table_rows.append([
            r.name,
            str(r.installed) if r.installed else "-",
            r.candidate or "-",
            r.required or "-",
            r.status.value,
        ])

    print(_format_table(["Tool", "Installed", "Candidate", "Required", "Status"], table_rows))
    log_action("check", None, success=all_up_to_date, message=f"Checked {len(rows_data)} tools")
    return 0 if all_up_to_date else 1


def cmd_install(args: argparse.Namespace) -> int:
    """Handle `install` subcommand: install a single tool."""
    backend = get_backend()
    registry = load_registry(backend=backend.name)

    if args.tool not in registry:
        err = f"Unknown tool '{args.tool}'. Available: {', '.join(s.name for s in registry.all_tools())}"
        print(f"Error: {err}", file=sys.stderr)
        log_action("install", args.tool, success=False, dry_run=args.dry_run, message=err, error_kind="not_found")
        return 2

    tool = registry.get(args.tool)
    pkg = tool.pkg_name_for(backend.name)
    target_pkg = pkg or tool.pip_package

    if not target_pkg:
        err = f"Tool '{args.tool}' has no package defined for backend '{backend.name}'."
        print(f"Error: {err}", file=sys.stderr)
        log_action("install", args.tool, success=False, dry_run=args.dry_run, message=err, error_kind="not_found")
        return 2

    res = backend.install(target_pkg, version=args.version, dry_run=args.dry_run)
    print(res.message)
    log_action(
        "install",
        args.tool,
        success=res.success,
        dry_run=res.dry_run,
        command=res.command,
        message=res.message,
        error_kind=res.error_kind,
    )
    return 0 if res.success else 1


def cmd_update(args: argparse.Namespace) -> int:
    """Handle `update` subcommand: update a tool or all tools."""
    backend = get_backend()
    registry = load_registry(backend=backend.name)

    if args.all:
        results = update_all(registry, backend, dry_run=args.dry_run)
        any_failed = False
        for res in results:
            print(res.message)
            if not res.success:
                any_failed = True
            log_action(
                "update",
                None,
                success=res.success,
                dry_run=res.dry_run,
                command=res.command,
                message=res.message,
                error_kind=res.error_kind,
            )
        return 1 if any_failed else 0

    if not args.tool:
        print("Error: Specify a tool name or --all.", file=sys.stderr)
        return 2

    if args.tool not in registry:
        err = f"Unknown tool '{args.tool}'."
        print(f"Error: {err}", file=sys.stderr)
        log_action("update", args.tool, success=False, dry_run=args.dry_run, message=err, error_kind="not_found")
        return 2

    res = update(args.tool, registry, backend, dry_run=args.dry_run)
    print(res.message)
    log_action(
        "update",
        args.tool,
        success=res.success,
        dry_run=res.dry_run,
        command=res.command,
        message=res.message,
        error_kind=res.error_kind,
    )
    return 0 if res.success else 1


def cmd_refresh(args: argparse.Namespace) -> int:
    """Handle `refresh` subcommand: refresh package manager index."""
    backend = get_backend()
    if hasattr(backend, "refresh_index"):
        res = backend.refresh_index(dry_run=args.dry_run)
    else:
        from esim_tool_manager.backends.base import Result
        res = Result(
            success=True,
            message=f"Backend '{backend.name}' does not require index refresh.",
            command=[],
            dry_run=args.dry_run,
        )

    print(res.message)
    log_action(
        "refresh",
        None,
        success=res.success,
        dry_run=res.dry_run,
        command=res.command,
        message=res.message,
        error_kind=res.error_kind,
    )
    return 0 if res.success else 1


def cmd_deps(args: argparse.Namespace) -> int:
    """Handle `deps` subcommand: evaluate dependencies and print report and fixes."""
    backend = get_backend()
    registry = load_registry(backend=backend.name)
    report = check_dependencies(registry, backend)

    table_rows = []
    for item in report.items:
        table_rows.append([
            item.name,
            item.kind,
            item.status.value,
            item.found or "-",
            item.required or "-",
        ])

    print(_format_table(["Dependency", "Kind", "Status", "Found", "Required"], table_rows))

    non_ok = [it for it in report.items if it.status != DepStatus.OK]
    if non_ok:
        print("\nRecommended Fixes:")
        for it in non_ok:
            if it.fix:
                print(f"  * {it.name}: {it.fix}")

    log_action("deps", None, success=report.all_ok, message=f"Dependencies checked: all_ok={report.all_ok}")
    return 0 if report.all_ok else 1


def cmd_log(args: argparse.Namespace) -> int:
    """Handle `log` subcommand: pretty-print JSONL action log entries."""
    entries = read_log(tail=args.tail)
    if not entries:
        print("Action log is empty.")
        return 0

    for e in entries:
        ts = e.get("timestamp", "-")
        act = (e.get("action") or "-").upper()
        tool = f" [{e.get('tool')}]" if e.get("tool") else ""
        status = "SUCCESS" if e.get("success") else "FAILED"
        dry = " (DRY-RUN)" if e.get("dry_run") else ""
        msg = f" - {e.get('message')}" if e.get("message") else ""
        err = f" [error: {e.get('error_kind')}]" if e.get("error_kind") else ""
        print(f"[{ts}] {act}{tool} -> {status}{dry}{err}{msg}")
    return 0


def cmd_configure(args: argparse.Namespace) -> int:
    """Handle `configure` subcommand: detect tool paths and generate shell environment."""
    from esim_tool_manager.config_manager import configure, get_env_file, show_config

    if args.show:
        print(show_config())
        return 0

    backend = get_backend()
    registry = load_registry(backend=backend.name)

    res = configure(registry, dry_run=args.dry_run)

    if res.dry_run:
        print("Dry run: configuration would be generated with detected paths:")
        for name, p in res.resolved_paths.items():
            print(f"  * {name}: {p}")
        if res.warnings:
            print("\nWarnings:")
            for w in res.warnings:
                print(f"  ! {w}")
        log_action("configure", None, success=True, dry_run=True, message="Dry-run configure")
        return 0 if not res.warnings else 1

    print("Configuration updated successfully.")
    for f in res.files_written:
        print(f"  Written: {f}")

    if res.warnings:
        print("\nWarnings:")
        for w in res.warnings:
            print(f"  ! {w}")

    env_file = get_env_file()
    print("\nTo activate this environment in your current shell, run:")
    print(f"  source {env_file}")

    has_missing = bool(res.warnings)
    log_action(
        "configure",
        None,
        success=not has_missing,
        message=f"Configured with {len(res.resolved_paths)} paths, warnings={len(res.warnings)}",
    )
    return 1 if has_missing else 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the command line parser."""
    parser = argparse.ArgumentParser(
        prog="esim-tm",
        description="Automated Tool Manager for eSim",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed debug output and tracebacks on error",
    )

    subparsers = parser.add_subparsers(dest="subcommand", metavar="<command>")

    # list
    p_list = subparsers.add_parser("list", help="List all tools with versions and status")
    p_list.set_defaults(func=cmd_list)

    # check
    p_check = subparsers.add_parser("check", help="Check tool statuses (exits 1 if any tool is not up to date)")
    p_check.set_defaults(func=cmd_check)

    # install
    p_install = subparsers.add_parser("install", help="Install a tool")
    p_install.add_argument("tool", help="Name of the tool to install")
    p_install.add_argument("--version", help="Specific version to install", default=None)
    p_install.add_argument("--dry-run", action="store_true", help="Print command without executing")
    p_install.set_defaults(func=cmd_install)

    # update
    p_update = subparsers.add_parser("update", help="Update tools")
    p_update.add_argument("tool", nargs="?", help="Tool to update (or omit if using --all)")
    p_update.add_argument("--all", action="store_true", help="Update all registered tools")
    p_update.add_argument("--dry-run", action="store_true", help="Print command without executing")
    p_update.set_defaults(func=cmd_update)

    # refresh
    p_refresh = subparsers.add_parser("refresh", help="Refresh package manager index")
    p_refresh.add_argument("--dry-run", action="store_true", help="Print command without executing")
    p_refresh.set_defaults(func=cmd_refresh)

    # deps
    p_deps = subparsers.add_parser("deps", help="Check system, python, and tool dependencies")
    p_deps.set_defaults(func=cmd_deps)

    # log
    p_log = subparsers.add_parser("log", help="Display action log records")
    p_log.add_argument("--tail", type=int, default=None, help="Number of recent entries to show")
    p_log.set_defaults(func=cmd_log)

    # configure
    p_config = subparsers.add_parser("configure", help="Detect tool locations and generate environment file")
    p_config.add_argument("--dry-run", action="store_true", help="Print configuration without writing files")
    p_config.add_argument("--show", action="store_true", help="Display current configuration file contents")
    p_config.set_defaults(func=cmd_configure)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except (UnsupportedPlatformError, ConfigError, KeyError) as exc:
        if getattr(args, "verbose", False):
            traceback.print_exc()
        else:
            print(f"Error: {exc}", file=sys.stderr)
        log_action("error", None, success=False, message=str(exc), error_kind="config")
        return 2
    except Exception as exc:  # noqa: BLE001
        if getattr(args, "verbose", False):
            traceback.print_exc()
        else:
            print(f"Error: {exc}", file=sys.stderr)
        log_action("error", None, success=False, message=str(exc), error_kind="unknown")
        return 1
