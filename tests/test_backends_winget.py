"""tests/test_backends_winget.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for esim_tool_manager.backends.winget (mocked tests only).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from esim_tool_manager.backends.winget import WingetBackend

SUBPROCESS_RUN = "esim_tool_manager.backends.base.subprocess.run"
WINGET_SUBPROCESS_RUN = "esim_tool_manager.backends.winget.subprocess.run"
WHICH = "esim_tool_manager.backends.winget.shutil.which"


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestWingetBackend:

    def test_is_available(self):
        backend = WingetBackend()
        with patch(WHICH, return_value="C:\\Windows\\winget.exe"):
            assert backend.is_available() is True
        with patch(WHICH, return_value=None):
            assert backend.is_available() is False

    def test_dry_run_executes_nothing(self):
        backend = WingetBackend()
        with patch(SUBPROCESS_RUN) as mock_sub:
            res = backend.install("KiCad.KiCad", dry_run=True)
            assert res.success is True
            assert res.dry_run is True
            assert "Dry run:" in res.message
            assert res.command[:4] == ["winget", "install", "--id", "KiCad.KiCad"]
            mock_sub.assert_not_called()

    def test_install_basic(self):
        backend = WingetBackend()
        with patch(SUBPROCESS_RUN, return_value=_proc(stdout="Successfully installed")) as mock_sub:
            res = backend.install("KiCad.KiCad")
            assert res.success is True
            assert res.command == [
                "winget",
                "install",
                "--id",
                "KiCad.KiCad",
                "--exact",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
            mock_sub.assert_called_once()

    def test_install_pinned_version(self):
        backend = WingetBackend()
        with patch(SUBPROCESS_RUN, return_value=_proc(stdout="Successfully installed")):
            res = backend.install("KiCad.KiCad", version="7.0.10")
            assert res.success is True
            assert "--version" in res.command
            assert "7.0.10" in res.command

    def test_upgrade(self):
        backend = WingetBackend()
        with patch(SUBPROCESS_RUN, return_value=_proc(stdout="Successfully updated")):
            res = backend.upgrade("KiCad.KiCad")
            assert res.success is True
            assert res.command[1] == "upgrade"

    def test_candidate_version(self):
        sample = """
Found KiCad [KiCad.KiCad]
Version: 7.0.10-1
Publisher: KiCad
"""
        backend = WingetBackend()
        with patch(WINGET_SUBPROCESS_RUN, return_value=_proc(stdout=sample)):
            ver = backend.candidate_version("KiCad.KiCad")
            assert ver == "7.0.10"

    def test_candidate_version_not_found(self):
        backend = WingetBackend()
        with patch(WINGET_SUBPROCESS_RUN, return_value=_proc(stdout="No package found", returncode=1)):
            assert backend.candidate_version("Invalid.App") is None
