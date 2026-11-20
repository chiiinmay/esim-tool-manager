"""tests/test_deps.py
~~~~~~~~~~~~~~~~~~
Unit tests for esim_tool_manager.deps.
"""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from packaging.version import Version

from esim_tool_manager.backends.base import Backend, Result
from esim_tool_manager.config import load_registry
from esim_tool_manager.deps import DepStatus, check_dependencies
from esim_tool_manager.versioning import VersionResult


class FakeBackend(Backend):
    name = "apt"

    def is_available(self) -> bool:
        return True

    def candidate_version(self, pkg: str) -> str | None:
        return "1.0.0"

    def install(self, pkg: str, version: str | None = None, dry_run: bool = False) -> Result:
        return Result(success=True, message="ok", command=[], dry_run=dry_run)

    def upgrade(self, pkg: str, dry_run: bool = False) -> Result:
        return Result(success=True, message="ok", command=[], dry_run=dry_run)


MINI_YAML = """
tools:
  - name: ngspice
    display_name: "Ngspice"
    kind: system
    version_cmd: "ngspice --version"
    version_regex: 'ngspice-(\\d+)'
    min_version: "37"
    latest_stable: ""
    depends_on: []
    pkg_name_apt: ngspice
    pkg_name_winget: "ngspice.ngspice"
    pip_package: ""
    install_notes: ""
  - name: numpy
    display_name: "NumPy"
    kind: pip
    version_cmd: 'python3 -c "import numpy; print(numpy.__version__)"'
    version_regex: '(\\d+\\.\\d+\\.\\d+)'
    min_version: "1.23.0"
    latest_stable: ""
    depends_on: []
    pkg_name_apt: python3-numpy
    pkg_name_winget: ""
    pip_package: numpy
    install_notes: ""
"""

GET_INSTALLED = "esim_tool_manager.deps.get_installed_version"
SUBPROCESS_RUN = "esim_tool_manager.deps.subprocess.run"
IMPORTLIB_VERSION = "importlib.metadata.version"


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestDependencyChecker:

    def test_all_ok(self, tmp_path):
        p = tmp_path / "tools.yaml"
        p.write_text(MINI_YAML, encoding="utf-8")
        reg = load_registry(path=p, backend="apt")
        backend = FakeBackend()

        with patch(SUBPROCESS_RUN, return_value=_proc(stdout="pip 24.0")), \
             patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("42"))), \
             patch(IMPORTLIB_VERSION, return_value="1.24.0"):
            report = check_dependencies(reg, backend)
            assert report.all_ok is True
            assert len(report.missing) == 0
            assert len(report.incompatible) == 0

    def test_python_too_old(self, tmp_path):
        p = tmp_path / "tools.yaml"
        p.write_text(MINI_YAML, encoding="utf-8")
        reg = load_registry(path=p, backend="apt")
        backend = FakeBackend()

        with patch.object(sys, "version_info", (3, 7, 9, "final", 0)), \
             patch(SUBPROCESS_RUN, return_value=_proc(stdout="pip 24.0")), \
             patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("42"))), \
             patch(IMPORTLIB_VERSION, return_value="1.24.0"):
            report = check_dependencies(reg, backend)
            assert report.all_ok is False
            py_item = next(it for it in report.items if it.name == "python")
            assert py_item.status == DepStatus.INCOMPATIBLE
            assert py_item.found == "3.7.9"
            assert "Python 3.8 or higher" in str(py_item.fix)

    def test_pip_unavailable(self, tmp_path):
        p = tmp_path / "tools.yaml"
        p.write_text(MINI_YAML, encoding="utf-8")
        reg = load_registry(path=p, backend="apt")
        backend = FakeBackend()

        with patch(SUBPROCESS_RUN, side_effect=FileNotFoundError), \
             patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("42"))), \
             patch(IMPORTLIB_VERSION, return_value="1.24.0"):
            report = check_dependencies(reg, backend)
            assert report.all_ok is False
            pip_item = next(it for it in report.items if it.name == "pip")
            assert pip_item.status == DepStatus.MISSING
            assert pip_item.fix == "sudo apt-get install -y python3-pip"

    def test_system_tool_missing_and_fix_command(self, tmp_path):
        p = tmp_path / "tools.yaml"
        p.write_text(MINI_YAML, encoding="utf-8")
        reg = load_registry(path=p, backend="apt")
        backend = FakeBackend()

        with patch(SUBPROCESS_RUN, return_value=_proc(stdout="pip 24.0")), \
             patch(GET_INSTALLED, return_value=VersionResult(status="not_installed", raw_output="", version=None)), \
             patch(IMPORTLIB_VERSION, return_value="1.24.0"):
            report = check_dependencies(reg, backend)
            assert report.all_ok is False
            tool_item = next(it for it in report.items if it.name == "ngspice")
            assert tool_item.status == DepStatus.MISSING
            # Fix should be built with min_version if available
            assert tool_item.fix == "sudo apt-get install -y ngspice=37"

    def test_system_tool_incompatible_version(self, tmp_path):
        p = tmp_path / "tools.yaml"
        p.write_text(MINI_YAML, encoding="utf-8")
        reg = load_registry(path=p, backend="apt")
        backend = FakeBackend()

        with patch(SUBPROCESS_RUN, return_value=_proc(stdout="pip 24.0")), \
             patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("35"))), \
             patch(IMPORTLIB_VERSION, return_value="1.24.0"):
            report = check_dependencies(reg, backend)
            assert report.all_ok is False
            tool_item = next(it for it in report.items if it.name == "ngspice")
            assert tool_item.status == DepStatus.INCOMPATIBLE
            assert tool_item.found == "35"
            assert tool_item.fix == "sudo apt-get install -y ngspice=37"

    def test_pip_package_missing_and_pep668_fix(self, tmp_path):
        p = tmp_path / "tools.yaml"
        p.write_text(MINI_YAML, encoding="utf-8")
        reg = load_registry(path=p, backend="apt")
        backend = FakeBackend()

        with patch(SUBPROCESS_RUN, return_value=_proc(stdout="pip 24.0")), \
             patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("42"))), \
             patch(IMPORTLIB_VERSION, side_effect=importlib.metadata.PackageNotFoundError):
            report = check_dependencies(reg, backend)
            assert report.all_ok is False
            pip_pkg_item = next(it for it in report.items if it.name == "numpy")
            assert pip_pkg_item.status == DepStatus.MISSING
            # numpy has pkg_name_apt: python3-numpy -> suggests apt package under PEP 668
            assert pip_pkg_item.fix == "sudo apt-get install -y python3-numpy"

    def test_pip_package_incompatible_version(self, tmp_path):
        p = tmp_path / "tools.yaml"
        p.write_text(MINI_YAML, encoding="utf-8")
        reg = load_registry(path=p, backend="apt")
        backend = FakeBackend()

        with patch(SUBPROCESS_RUN, return_value=_proc(stdout="pip 24.0")), \
             patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("42"))), \
             patch(IMPORTLIB_VERSION, return_value="1.20.0"):
            report = check_dependencies(reg, backend)
            assert report.all_ok is False
            pip_pkg_item = next(it for it in report.items if it.name == "numpy")
            assert pip_pkg_item.status == DepStatus.INCOMPATIBLE
            assert pip_pkg_item.found == "1.20.0"
            assert pip_pkg_item.required == ">=1.23.0"
            assert pip_pkg_item.fix == "sudo apt-get install -y python3-numpy"

    def test_pip_package_no_apt_pkg_suggests_venv(self, tmp_path):
        # Package with no apt mapping (e.g. hdlparse)
        custom_yaml = """
tools:
  - name: hdlparse
    display_name: "HDLParse"
    kind: pip
    version_cmd: 'python3 -c "import hdlparse"'
    version_regex: '(\\d+\\.\\d+)'
    min_version: "0.1"
    latest_stable: ""
    depends_on: []
    pkg_name_apt: ""
    pkg_name_winget: ""
    pip_package: hdlparse
    install_notes: ""
"""
        p = tmp_path / "tools.yaml"
        p.write_text(custom_yaml, encoding="utf-8")
        reg = load_registry(path=p, backend="apt")
        backend = FakeBackend()

        with patch(SUBPROCESS_RUN, return_value=_proc(stdout="pip 24.0")), \
             patch(IMPORTLIB_VERSION, side_effect=importlib.metadata.PackageNotFoundError):
            report = check_dependencies(reg, backend)
            hdl_item = next(it for it in report.items if it.name == "hdlparse")
            assert hdl_item.status == DepStatus.MISSING
            assert ".venv" in str(hdl_item.fix)
            assert "pip install hdlparse" in str(hdl_item.fix)

    def test_winget_fix_command(self, tmp_path):
        p = tmp_path / "tools.yaml"
        p.write_text(MINI_YAML, encoding="utf-8")
        reg = load_registry(path=p, backend="winget")

        class FakeWingetBackend(Backend):
            name = "winget"
            def is_available(self): return True
            def candidate_version(self, pkg): return "1.0"
            def install(self, pkg, version=None, dry_run=False): return Result(True, "", [], dry_run)
            def upgrade(self, pkg, dry_run=False): return Result(True, "", [], dry_run)

        backend = FakeWingetBackend()
        with patch(SUBPROCESS_RUN, return_value=_proc(stdout="pip 24.0")), \
             patch(GET_INSTALLED, return_value=VersionResult(status="not_installed", raw_output="", version=None)), \
             patch(IMPORTLIB_VERSION, return_value="1.24.0"):
            report = check_dependencies(reg, backend)
            ng_item = next(it for it in report.items if it.name == "ngspice")
            assert "winget install --id ngspice.ngspice" in str(ng_item.fix)
