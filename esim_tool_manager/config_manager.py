"""esim_tool_manager.config_manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Generates and manages ~/.esim_tm/config.yaml and shell environment files
(env.sh for POSIX, env.ps1 for Windows).
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
from typing import TYPE_CHECKING

import yaml

from esim_tool_manager.logger import get_log_dir
from esim_tool_manager.platform_detect import detect_os

if TYPE_CHECKING:
    from esim_tool_manager.config import Registry


@dataclass(frozen=True)
class ConfigResult:
    """Result of running `configure`."""

    paths_detected: dict[str, str | None]
    resolved_paths: dict[str, str]
    warnings: list[str]
    files_written: list[str]
    dry_run: bool


def get_config_file() -> Path:
    """Return path to config.yaml."""
    return get_log_dir() / "config.yaml"


def get_env_file() -> Path:
    """Return path to env.sh (or env.ps1 on Windows)."""
    if detect_os() == "windows":
        return get_log_dir() / "env.ps1"
    return get_log_dir() / "env.sh"


def detect_tool_paths(registry: Registry) -> dict[str, str | None]:
    """Detect filesystem path for each tool's executable via shutil.which.

    Missing tools or tools without an executable map to None.
    """
    detected: dict[str, str | None] = {}
    for tool in registry.all_tools():
        exe = tool.executable or (tool.name if tool.kind == "system" else "")
        if not exe:
            detected[tool.name] = None
            continue

        loc = shutil.which(exe)
        detected[tool.name] = str(Path(loc).resolve()) if loc else None

    return detected


def _atomic_write(target_path: Path, content: str) -> None:
    """Write content to target_path atomically using a tempfile in the same dir."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_file = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".tmp_",
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(temp_file, target_path)
    finally:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass


def generate_env_file(resolved_paths: dict[str, str]) -> str:
    """Generate shell environment script exporting paths and deduplicated PATH prepend.

    For POSIX systems (Linux/macOS), generates a bash script.
    Quotes all paths using shlex.quote to prevent syntax breakage or command injection.
    """
    os_name = detect_os()
    if os_name == "windows":
        # Windows PowerShell env.ps1
        # NOTE: Untested on real Windows.
        lines = [
            "# eSim Tool Manager Environment Setup for PowerShell",
            "# Source this script with: . ~/.esim_tm/env.ps1",
            "",
        ]
        dirs_to_prepend: list[str] = []
        for name, p in resolved_paths.items():
            if not p:
                continue
            parent_dir = str(Path(p).parent)
            if parent_dir not in dirs_to_prepend:
                dirs_to_prepend.append(parent_dir)

            var_name = f"ESIM_TM_{name.upper().replace('-', '_')}_PATH"  # VERIFY: matches expected eSim variable
            safe_p = p.replace("'", "''")
            lines.append(f"$env:{var_name} = '{safe_p}'")

        if dirs_to_prepend:
            lines.append("")
            lines.append("# Deduplicated PATH prepend")
            for d in reversed(dirs_to_prepend):
                safe_d = d.replace("'", "''")
                lines.append(f"if ($env:PATH -notlike '*{safe_d}*') {{ $env:PATH = '{safe_d};' + $env:PATH }}")

        lines.append("")
        return "\n".join(lines)

    # POSIX bash env.sh
    lines = [
        "#!/usr/bin/env bash",
        "# eSim Tool Manager Environment Setup",
        "# Source this script with: source ~/.esim_tm/env.sh",
        "",
    ]

    dirs_to_prepend = []
    for name, p in resolved_paths.items():
        if not p:
            continue
        parent_dir = str(Path(p).parent).replace("\\", "/")
        if parent_dir not in dirs_to_prepend:
            dirs_to_prepend.append(parent_dir)

        var_name = f"ESIM_TM_{name.upper().replace('-', '_')}_PATH"  # VERIFY: matches expected eSim variable
        lines.append(f"export {var_name}={shlex.quote(p)}")

    if dirs_to_prepend:
        lines.append("")
        lines.append("# Deduplicated PATH prepend")
        for d in reversed(dirs_to_prepend):
            quoted_dir = shlex.quote(d)
            lines.append(f'case ":$PATH:" in')
            lines.append(f'  *":{d}:"*) ;;')
            lines.append(f'  *) export PATH={quoted_dir}:"$PATH" ;;')
            lines.append(f"esac")

    lines.append("")
    return "\n".join(lines)


def configure(registry: Registry, dry_run: bool = False) -> ConfigResult:
    """Run configuration generation.

    Detects tool paths, loads and preserves user overrides in config.yaml,
    validates overrides, produces env script, and saves files atomically.
    Dry-run mode makes NO filesystem modifications.
    """
    detected = detect_tool_paths(registry)
    config_file = get_config_file()
    env_file = get_env_file()

    overrides: dict[str, str] = {}
    settings: dict = {}

    # Load existing config if available
    if config_file.is_file():
        try:
            with config_file.open("r", encoding="utf-8") as fh:
                existing_data = yaml.safe_load(fh)
                if isinstance(existing_data, dict):
                    raw_overrides = existing_data.get("overrides", {})
                    if isinstance(raw_overrides, dict):
                        overrides = {str(k): str(v) for k, v in raw_overrides.items()}
                    raw_settings = existing_data.get("settings", {})
                    if isinstance(raw_settings, dict):
                        settings = raw_settings
        except Exception as exc:
            raise ValueError(f"Corrupt config file at {config_file}: {exc}") from exc

    warnings: list[str] = []
    resolved: dict[str, str] = {}

    for tool in registry.all_tools():
        name = tool.name
        det_path = detected.get(name)

        if name in overrides:
            cand = overrides[name]
            if os.path.exists(cand):
                resolved[name] = str(Path(cand).resolve())
            else:
                warnings.append(
                    f"Override path for '{name}' does not exist: {cand}. Falling back to detected path."
                )
                if det_path:
                    resolved[name] = det_path
        else:
            if det_path:
                resolved[name] = det_path

    for tool in registry.all_tools():
        if tool.kind == "system" and tool.name not in resolved:
            warnings.append(f"System tool '{tool.name}' not found on system.")

    config_data = {
        "detected": detected,
        "overrides": overrides,
        "settings": settings,
    }
    config_yaml_str = yaml.safe_dump(config_data, sort_keys=False)
    env_script_str = generate_env_file(resolved)

    files_written: list[str] = []
    if not dry_run:
        _atomic_write(config_file, config_yaml_str)
        files_written.append(str(config_file))
        _atomic_write(env_file, env_script_str)
        files_written.append(str(env_file))

    return ConfigResult(
        paths_detected=detected,
        resolved_paths=resolved,
        warnings=warnings,
        files_written=files_written,
        dry_run=dry_run,
    )


def show_config() -> str:
    """Return the raw config.yaml contents, or an instructional message if not configured."""
    config_file = get_config_file()
    if not config_file.is_file():
        return (
            "Configuration has not been generated yet.\n"
            "Run `esim-tm configure` to detect tool paths and generate configuration."
        )

    try:
        with config_file.open("r", encoding="utf-8") as fh:
            return fh.read()
    except Exception as exc:
        raise ValueError(f"Failed to read config file at {config_file}: {exc}") from exc
