"""tests/test_logger.py
~~~~~~~~~~~~~~~~~~~~
Unit tests for esim_tool_manager.logger.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from esim_tool_manager.logger import (
    _LOGGER_NAME,
    get_log_dir,
    get_log_file,
    log_action,
    read_log,
)


@pytest.fixture(autouse=True)
def clean_logger(tmp_path, monkeypatch):
    """Ensure a fresh logger instance per test pointed to tmp_path."""
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / ".esim_tm"))
    logger = logging.getLogger(_LOGGER_NAME)
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)
    yield
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


class TestLogger:

    def test_log_action_writes_valid_json(self):
        log_action(
            action="install",
            tool="ngspice",
            success=True,
            dry_run=False,
            command=["apt-get", "install", "-y", "ngspice"],
            message="Installed successfully",
            error_kind=None,
        )

        log_file = get_log_file()
        assert log_file.is_file()

        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["action"] == "install"
        assert record["tool"] == "ngspice"
        assert record["success"] is True
        assert record["dry_run"] is False
        assert record["command"] == ["apt-get", "install", "-y", "ngspice"]
        assert record["message"] == "Installed successfully"
        assert record["error_kind"] is None
        assert "timestamp" in record

    def test_unwritable_directory_swallows_error(self, monkeypatch, capsys):
        # Point ESIM_TM_HOME to a file path so mkdir fails
        bad_dir = Path(get_log_dir().parent) / "a_file_here"
        bad_dir.write_text("blocking file", encoding="utf-8")
        monkeypatch.setenv("ESIM_TM_HOME", str(bad_dir / "nested"))

        # Should NOT raise
        log_action(
            action="error",
            tool=None,
            success=False,
            message="Should swallow error",
        )

        captured = capsys.readouterr()
        assert "Warning: Failed" in captured.err

    def test_read_log_skips_malformed_lines(self):
        log_file = get_log_file()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        good_entry = json.dumps({"action": "install", "tool": "ghdl", "success": True})
        log_file.write_text(f"{good_entry}\nNOT_VALID_JSON\n{good_entry}\n", encoding="utf-8")

        entries = read_log()
        assert len(entries) == 2
        assert entries[0]["tool"] == "ghdl"
        assert entries[1]["tool"] == "ghdl"

    def test_read_log_tail(self):
        log_file = get_log_file()
        log_file.parent.mkdir(parents=True, exist_ok=True)

        lines = []
        for i in range(10):
            lines.append(json.dumps({"id": i}))
        log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        last_3 = read_log(tail=3)
        assert len(last_3) == 3
        assert [e["id"] for e in last_3] == [7, 8, 9]

    def test_read_log_empty_or_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / "empty_dir"))
        assert read_log() == []
