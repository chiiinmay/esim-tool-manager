"""tests/test_cli.py
~~~~~~~~~~~~~~~~~
Unit tests for esim_tool_manager.cli.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from packaging.version import Version

from esim_tool_manager import __version__
from esim_tool_manager.backends.base import Result
from esim_tool_manager.cli import main
from esim_tool_manager.deps import DepItem, DepReport, DepStatus
from esim_tool_manager.logger import _LOGGER_NAME, log_action
from esim_tool_manager.platform_detect import UnsupportedPlatformError
from esim_tool_manager.updater import UpdateRow, UpdateStatus


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


class TestCli:

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert f"esim-tm {__version__}" in captured.out

    def test_no_args_prints_help(self, capsys):
        code = main([])
        assert code == 0
        captured = capsys.readouterr()
        assert "Automated Tool Manager for eSim" in captured.out

    def test_list_command(self, capsys):
        mock_backend = MagicMock(name="mock_backend")
        mock_backend.name = "apt"
        mock_rows = [
            UpdateRow("ngspice", Version("42"), "42", "37", UpdateStatus.UP_TO_DATE),
            UpdateRow("kicad", None, "7.0.10", "7.0.0", UpdateStatus.NOT_INSTALLED),
        ]

        with patch("esim_tool_manager.cli.get_backend", return_value=mock_backend), \
             patch("esim_tool_manager.cli.load_registry"), \
             patch("esim_tool_manager.cli.check_updates", return_value=mock_rows):
            code = main(["list"])
            assert code == 0
            captured = capsys.readouterr()
            assert "ngspice" in captured.out
            assert "up_to_date" in captured.out
            assert "kicad" in captured.out
            assert "not_installed" in captured.out

    def test_check_command_fails_when_not_up_to_date(self, capsys):
        mock_backend = MagicMock(name="mock_backend")
        mock_backend.name = "apt"
        mock_rows = [
            UpdateRow("ngspice", Version("35"), "42", "37", UpdateStatus.BELOW_MINIMUM),
        ]

        with patch("esim_tool_manager.cli.get_backend", return_value=mock_backend), \
             patch("esim_tool_manager.cli.load_registry"), \
             patch("esim_tool_manager.cli.check_updates", return_value=mock_rows):
            code = main(["check"])
            assert code == 1
            captured = capsys.readouterr()
            assert "below_minimum" in captured.out

    def test_install_unknown_tool_returns_2(self, capsys):
        mock_backend = MagicMock(name="mock_backend")
        mock_backend.name = "apt"
        mock_reg = MagicMock()
        mock_reg.__contains__.return_value = False
        mock_reg.all_tools.return_value = []

        with patch("esim_tool_manager.cli.get_backend", return_value=mock_backend), \
             patch("esim_tool_manager.cli.load_registry", return_value=mock_reg):
            code = main(["install", "invalid_tool"])
            assert code == 2
            captured = capsys.readouterr()
            assert "Unknown tool 'invalid_tool'" in captured.err

    def test_install_dry_run_logs_and_returns_0(self, capsys):
        mock_backend = MagicMock(name="mock_backend")
        mock_backend.name = "apt"
        mock_backend.install.return_value = Result(
            success=True,
            message="Dry run: would execute apt-get install ngspice",
            command=["apt-get", "install", "ngspice"],
            dry_run=True,
        )

        mock_tool = MagicMock()
        mock_tool.pkg_name_for.return_value = "ngspice"
        mock_reg = MagicMock()
        mock_reg.__contains__.return_value = True
        mock_reg.get.return_value = mock_tool

        with patch("esim_tool_manager.cli.get_backend", return_value=mock_backend), \
             patch("esim_tool_manager.cli.load_registry", return_value=mock_reg):
            code = main(["install", "ngspice", "--dry-run"])
            assert code == 0
            captured = capsys.readouterr()
            assert "Dry run:" in captured.out
            mock_backend.install.assert_called_with("ngspice", version=None, dry_run=True)

    def test_update_all_subcommand(self, capsys):
        mock_backend = MagicMock(name="mock_backend")
        mock_backend.name = "apt"
        mock_reg = MagicMock()
        mock_results = [
            Result(True, "ngspice up to date", [], False),
            Result(True, "kicad upgraded", [], False),
        ]

        with patch("esim_tool_manager.cli.get_backend", return_value=mock_backend), \
             patch("esim_tool_manager.cli.load_registry", return_value=mock_reg), \
             patch("esim_tool_manager.cli.update_all", return_value=mock_results):
            code = main(["update", "--all"])
            assert code == 0
            captured = capsys.readouterr()
            assert "ngspice up to date" in captured.out
            assert "kicad upgraded" in captured.out

    def test_deps_subcommand(self, capsys):
        mock_backend = MagicMock(name="mock_backend")
        mock_backend.name = "apt"
        mock_reg = MagicMock()
        report = DepReport(
            items=[
                DepItem("python", "python", DepStatus.OK, "3.11.9", ">=3.8.0", None),
                DepItem("ngspice", "tool", DepStatus.MISSING, None, ">=37", "sudo apt-get install -y ngspice=37"),
            ]
        )

        with patch("esim_tool_manager.cli.get_backend", return_value=mock_backend), \
             patch("esim_tool_manager.cli.load_registry", return_value=mock_reg), \
             patch("esim_tool_manager.cli.check_dependencies", return_value=report):
            code = main(["deps"])
            assert code == 1
            captured = capsys.readouterr()
            assert "ngspice" in captured.out
            assert "missing" in captured.out
            assert "sudo apt-get install -y ngspice=37" in captured.out

    def test_log_subcommand(self, capsys):
        log_action("install", "ngspice", True, False, ["apt-get", "install"], "Success message")
        code = main(["log", "--tail", "1"])
        assert code == 0
        captured = capsys.readouterr()
        assert "INSTALL" in captured.out
        assert "[ngspice]" in captured.out
        assert "SUCCESS" in captured.out

    def test_unsupported_platform_clean_message_unless_verbose(self, capsys):
        with patch("esim_tool_manager.cli.get_backend", side_effect=UnsupportedPlatformError("No backend")):
            code = main(["list"])
            assert code == 2
            captured = capsys.readouterr()
            assert "Error: No backend" in captured.err
            assert "Traceback" not in captured.err

        with patch("esim_tool_manager.cli.get_backend", side_effect=UnsupportedPlatformError("No backend")):
            code = main(["--verbose", "list"])
            assert code == 2
            captured = capsys.readouterr()
            assert "Traceback" in captured.err
