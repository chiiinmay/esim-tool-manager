"""tests/test_backends_apt.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for esim_tool_manager.backends.apt.

Subprocess and platform functions are strictly mocked.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from esim_tool_manager.backends.apt import AptBackend


SUBPROCESS_RUN = "esim_tool_manager.backends.base.subprocess.run"
APT_SUBPROCESS_RUN = "esim_tool_manager.backends.apt.subprocess.run"
WHICH = "esim_tool_manager.backends.apt.shutil.which"
GETEUID = "esim_tool_manager.backends.apt.geteuid"


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestAptBackend:

    def test_is_available(self):
        backend = AptBackend()
        with patch(WHICH, return_value="/usr/bin/apt-get"):
            assert backend.is_available() is True
        with patch(WHICH, return_value=None):
            assert backend.is_available() is False

    def test_dry_run_executes_nothing(self):
        backend = AptBackend()
        with patch(GETEUID, return_value=0), \
             patch(SUBPROCESS_RUN) as mock_sub:
            res = backend.install("ngspice", dry_run=True)
            assert res.success is True
            assert res.dry_run is True
            assert "Dry run:" in res.message
            assert res.command == ["apt-get", "install", "-y", "ngspice"]
            mock_sub.assert_not_called()

    def test_install_root(self):
        backend = AptBackend()
        with patch(GETEUID, return_value=0), \
             patch(SUBPROCESS_RUN, return_value=_proc(stdout="Setting up ngspice")) as mock_sub:
            res = backend.install("ngspice")
            assert res.success is True
            assert res.command == ["apt-get", "install", "-y", "ngspice"]
            assert mock_sub.call_count == 1
            args, kwargs = mock_sub.call_args
            assert args[0] == ["apt-get", "install", "-y", "ngspice"]
            assert kwargs["env"]["DEBIAN_FRONTEND"] == "noninteractive"

    def test_install_pinned_version(self):
        backend = AptBackend()
        with patch(GETEUID, return_value=0), \
             patch(SUBPROCESS_RUN, return_value=_proc(stdout="Setting up ngspice")):
            res = backend.install("ngspice", version="42")
            assert res.success is True
            assert res.command == ["apt-get", "install", "-y", "ngspice=42"]

    def test_install_sudo_non_root(self):
        backend = AptBackend()
        with patch(GETEUID, return_value=1000), \
             patch(WHICH, return_value="/usr/bin/sudo"), \
             patch(SUBPROCESS_RUN, return_value=_proc(stdout="OK")):
            res = backend.install("ngspice")
            assert res.success is True
            assert res.command == ["sudo", "apt-get", "install", "-y", "ngspice"]

    def test_install_no_sudo_non_root_returns_permission_error(self):
        backend = AptBackend()
        with patch(GETEUID, return_value=1000), \
             patch(WHICH, return_value=None), \
             patch(SUBPROCESS_RUN) as mock_sub:
            res = backend.install("ngspice")
            assert res.success is False
            assert res.error_kind == "permission"
            assert "requires root privileges" in res.message
            mock_sub.assert_not_called()

    def test_upgrade_uses_only_upgrade(self):
        backend = AptBackend()
        with patch(GETEUID, return_value=0), \
             patch(SUBPROCESS_RUN, return_value=_proc(stdout="Upgraded")):
            res = backend.upgrade("kicad")
            assert res.success is True
            assert res.command == ["apt-get", "install", "-y", "--only-upgrade", "kicad"]

    def test_refresh_index(self):
        backend = AptBackend()
        with patch(GETEUID, return_value=0), \
             patch(SUBPROCESS_RUN, return_value=_proc(stdout="Fetched")):
            res = backend.refresh_index()
            assert res.success is True
            assert res.command == ["apt-get", "update"]

    def test_candidate_version_real_sample(self):
        sample = """
ngspice:
  Installed: (none)
  Candidate: 42+ds-1
  Version table:
     42+ds-1 500
        500 http://archive.ubuntu.com/ubuntu noble/universe amd64 Packages
"""
        backend = AptBackend()
        with patch(APT_SUBPROCESS_RUN, return_value=_proc(stdout=sample)):
            cand = backend.candidate_version("ngspice")
            # 42+ds-1 should be normalized to 42
            assert cand == "42"

    def test_candidate_version_none_case(self):
        sample = """
nonexistent-pkg:
  Installed: (none)
  Candidate: (none)
  Version table:
"""
        backend = AptBackend()
        with patch(APT_SUBPROCESS_RUN, return_value=_proc(stdout=sample)):
            assert backend.candidate_version("nonexistent-pkg") is None

    def test_candidate_version_missing_command_or_nonzero(self):
        backend = AptBackend()
        with patch(APT_SUBPROCESS_RUN, side_effect=FileNotFoundError):
            assert backend.candidate_version("ngspice") is None

        with patch(APT_SUBPROCESS_RUN, return_value=_proc(returncode=1)):
            assert backend.candidate_version("ngspice") is None

    def test_network_failure_classification(self):
        backend = AptBackend()
        err_msg = "Err:1 http://archive.ubuntu.com/ubuntu noble InRelease\n  Could not resolve 'archive.ubuntu.com'"
        with patch(GETEUID, return_value=0), \
             patch(SUBPROCESS_RUN, return_value=_proc(stderr=err_msg, returncode=100)):
            res = backend.install("ngspice")
            assert res.success is False
            assert res.error_kind == "network"

    def test_not_found_classification(self):
        backend = AptBackend()
        err_msg = "E: Unable to locate package invalid-pkg-xyz"
        with patch(GETEUID, return_value=0), \
             patch(SUBPROCESS_RUN, return_value=_proc(stderr=err_msg, returncode=100)):
            res = backend.install("invalid-pkg-xyz")
            assert res.success is False
            assert res.error_kind == "not_found"

    def test_timeout_handling(self):
        backend = AptBackend()
        with patch(GETEUID, return_value=0), \
             patch(SUBPROCESS_RUN, side_effect=subprocess.TimeoutExpired(cmd=["apt-get"], timeout=300)):
            res = backend.install("ngspice")
            assert res.success is False
            assert "timed out after 300 seconds" in res.message
            assert res.error_kind == "unknown"
