"""esim_tool_manager.logger
~~~~~~~~~~~~~~~~~~~~~~~~
Action logger writing newline-delimited JSON entries to a rotating log file.
Console output is separate and human-readable.
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from typing import Literal

ActionType = Literal["install", "update", "check", "deps", "refresh", "error", "configure"]

_LOGGER_NAME = "esim_tm_action_logger"


def get_log_dir() -> Path:
    """Return the base directory for esim-tm log files.

    Can be overridden via the ESIM_TM_HOME environment variable.
    """
    custom_home = os.environ.get("ESIM_TM_HOME")
    if custom_home:
        return Path(custom_home)
    return Path.home() / ".esim_tm"


def get_log_file() -> Path:
    """Return the path to actions.log."""
    return get_log_dir() / "actions.log"


def _get_file_logger() -> logging.Logger | None:
    """Get or configure the rotating file logger.

    Never crashes; returns None if file/directory creation fails.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_path = get_log_file()
    # Check if existing handler already points to the current log_path
    for h in list(logger.handlers):
        if isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == log_path.resolve():
            return logger
        # Outdated handler (path changed, e.g. in test env)
        h.close()
        logger.removeHandler(h)

    log_dir = get_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        return logger
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: Failed to initialize log file at {log_dir}: {exc}", file=sys.stderr)
        return None


def log_action(
    action: ActionType,
    tool: str | None,
    success: bool,
    dry_run: bool = False,
    command: list[str] | None = None,
    message: str = "",
    error_kind: str | None = None,
) -> None:
    """Write one newline-delimited JSON record to the action log.

    Never raises an exception.
    """
    try:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "tool": tool,
            "success": success,
            "dry_run": dry_run,
            "command": command,
            "message": message,
            "error_kind": error_kind,
        }
        json_line = json.dumps(record)

        logger = _get_file_logger()
        if logger is not None:
            logger.info(json_line)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: Failed to write to action log: {exc}", file=sys.stderr)


def read_log(tail: int | None = None) -> list[dict]:
    """Read entries from the action log file.

    Skips malformed JSON lines instead of raising.
    If tail is provided, returns the last N records.
    """
    log_file = get_log_file()
    if not log_file.is_file():
        return []

    entries: list[dict] = []
    try:
        with log_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: Failed to read action log: {exc}", file=sys.stderr)
        return []

    if tail is not None and tail > 0:
        return entries[-tail:]
    return entries
