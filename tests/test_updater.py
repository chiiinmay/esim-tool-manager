"""tests/test_updater.py
~~~~~~~~~~~~~~~~~~~~~
Unit tests for esim_tool_manager.updater.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from packaging.version import Version

from esim_tool_manager.backends.base import Backend, Result
from esim_tool_manager.config import load_registry
from esim_tool_manager.updater import (
    UpdateRow,
    UpdateStatus,
    check_updates,
    update,
    update_all,
)
from esim_tool_manager.versioning import VersionResult


class FakeBackend(Backend):
    """Test fake for Backend."""

    name = "apt"

    def __init__(self, candidates: dict[str, str | None] | None = None):
        self.candidates = candidates or {}
        self.upgrade_calls: list[str] = []
        self.dry_run_calls: list[bool] = []

    def is_available(self) -> bool:
        return True

    def candidate_version(self, pkg: str) -> str | None:
        return self.candidates.get(pkg)

    def install(self, pkg: str, version: str | None = None, dry_run: bool = False) -> Result:
        return Result(success=True, message=f"Installed {pkg}", command=["install", pkg], dry_run=dry_run)

    def upgrade(self, pkg: str, dry_run: bool = False) -> Result:
        self.upgrade_calls.append(pkg)
        self.dry_run_calls.append(dry_run)
        return Result(success=True, message=f"Upgraded {pkg}", command=["upgrade", pkg], dry_run=dry_run)


def _make_reg(tmp_path, content: str):
    p = tmp_path / "tools.yaml"
    p.write_text(content, encoding="utf-8")
    return load_registry(path=p, backend="apt")


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
  - name: kicad
    display_name: "KiCad"
    kind: system
    version_cmd: "kicad --version"
    version_regex: '(\\d+\\.\\d+\\.\\d+)'
    min_version: "7.0.0"
    latest_stable: ""
    depends_on: []
    pkg_name_apt: kicad
    pkg_name_winget: "KiCad.KiCad"
    pip_package: ""
    install_notes: ""
"""

GET_INSTALLED = "esim_tool_manager.updater.get_installed_version"


class TestUpdaterCheckUpdates:

    def test_up_to_date(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": "42", "kicad": "7.0.10"})
        with patch(GET_INSTALLED, side_effect=[
            VersionResult(status="installed", raw_output="", version=Version("42")),
            VersionResult(status="installed", raw_output="", version=Version("7.0.10")),
        ]):
            rows = check_updates(reg, fake_b)
            assert len(rows) == 2
            assert rows[0].status == UpdateStatus.UP_TO_DATE
            assert rows[1].status == UpdateStatus.UP_TO_DATE

    def test_update_available(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": "44", "kicad": "7.0.10"})
        with patch(GET_INSTALLED, side_effect=[
            VersionResult(status="installed", raw_output="", version=Version("42")),
            VersionResult(status="installed", raw_output="", version=Version("7.0.10")),
        ]):
            rows = check_updates(reg, fake_b)
            assert rows[0].status == UpdateStatus.UPDATE_AVAILABLE
            assert rows[0].installed == Version("42")
            assert rows[0].candidate == "44"

    def test_not_installed(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": "42", "kicad": "7.0.10"})
        with patch(GET_INSTALLED, side_effect=[
            VersionResult(status="not_installed", raw_output="", version=None),
            VersionResult(status="installed", raw_output="", version=Version("7.0.10")),
        ]):
            rows = check_updates(reg, fake_b)
            assert rows[0].status == UpdateStatus.NOT_INSTALLED
            assert rows[0].installed is None

    def test_below_minimum_takes_priority(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": "42", "kicad": "7.0.10"})
        with patch(GET_INSTALLED, side_effect=[
            VersionResult(status="installed", raw_output="", version=Version("35")),
            VersionResult(status="installed", raw_output="", version=Version("7.0.10")),
        ]):
            rows = check_updates(reg, fake_b)
            assert rows[0].status == UpdateStatus.BELOW_MINIMUM
            assert rows[0].installed == Version("35")
            assert rows[0].candidate == "42"

    def test_unparsable_version(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": "42", "kicad": "7.0.10"})
        with patch(GET_INSTALLED, side_effect=[
            VersionResult(status="unparsable", raw_output="", version=None),
            VersionResult(status="installed", raw_output="", version=Version("7.0.10")),
        ]):
            rows = check_updates(reg, fake_b)
            assert rows[0].status == UpdateStatus.UNPARSABLE

    def test_unknown_candidate(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": None, "kicad": "7.0.10"})
        with patch(GET_INSTALLED, side_effect=[
            VersionResult(status="installed", raw_output="", version=Version("42")),
            VersionResult(status="installed", raw_output="", version=Version("7.0.10")),
        ]):
            rows = check_updates(reg, fake_b)
            assert rows[0].status == UpdateStatus.UNKNOWN_CANDIDATE


class TestUpdaterUpdate:

    def test_unknown_tool_name(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend()
        res = update("nonexistent_tool", reg, fake_b)
        assert res.success is False
        assert "Unknown tool" in res.message
        assert res.error_kind == "not_found"

    def test_not_installed_tells_user_to_install(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend()
        with patch(GET_INSTALLED, return_value=VersionResult(status="not_installed", raw_output="", version=None)):
            res = update("ngspice", reg, fake_b)
            assert res.success is False
            assert "is not installed" in res.message
            assert "esim-tm install ngspice" in res.message
            assert len(fake_b.upgrade_calls) == 0

    def test_already_up_to_date(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": "42"})
        with patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("42"))):
            res = update("ngspice", reg, fake_b)
            assert res.success is True
            assert "already up to date" in res.message
            assert len(fake_b.upgrade_calls) == 0

    def test_no_downgrade(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": "40"})
        with patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("42"))):
            res = update("ngspice", reg, fake_b)
            assert res.success is True
            assert "older than installed" in res.message
            assert "Will not downgrade" in res.message
            assert len(fake_b.upgrade_calls) == 0

    def test_candidate_none(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": None})
        with patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("42"))):
            res = update("ngspice", reg, fake_b)
            assert res.success is False
            assert "No candidate version found" in res.message
            assert "apt-get update" in res.message

    def test_upgrade_success(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": "44"})
        with patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("42"))):
            res = update("ngspice", reg, fake_b)
            assert res.success is True
            assert fake_b.upgrade_calls == ["ngspice"]
            assert fake_b.dry_run_calls == [False]

    def test_dry_run_passes_through(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": "44"})
        with patch(GET_INSTALLED, return_value=VersionResult(status="installed", raw_output="", version=Version("42"))):
            res = update("ngspice", reg, fake_b, dry_run=True)
            assert res.success is True
            assert fake_b.upgrade_calls == ["ngspice"]
            assert fake_b.dry_run_calls == [True]


class TestUpdaterUpdateAll:

    def test_continues_after_failure(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": "44", "kicad": "8.0.0"})

        def fake_upgrade(pkg, dry_run=False):
            if pkg == "ngspice":
                return Result(success=False, message="Failed ngspice", command=[], dry_run=dry_run, error_kind="network")
            return Result(success=True, message="Upgraded kicad", command=[], dry_run=dry_run)

        fake_b.upgrade = fake_upgrade

        with patch(GET_INSTALLED, side_effect=[
            VersionResult(status="installed", raw_output="", version=Version("42")),
            VersionResult(status="installed", raw_output="", version=Version("7.0.0")),
        ]):
            results = update_all(reg, fake_b)
            assert len(results) == 2
            assert results[0].success is False
            assert results[0].message == "Failed ngspice"
            assert results[1].success is True
            assert results[1].message == "Upgraded kicad"

    def test_hint_added_when_all_candidates_none(self, tmp_path):
        reg = _make_reg(tmp_path, MINI_YAML)
        fake_b = FakeBackend({"ngspice": None, "kicad": None})
        with patch(GET_INSTALLED, side_effect=[
            VersionResult(status="installed", raw_output="", version=Version("42")),
            VersionResult(status="installed", raw_output="", version=Version("7.0.0")),
        ]):
            results = update_all(reg, fake_b)
            # 2 tool update results + 1 hint result
            assert len(results) == 3
            assert "Hint: Candidate versions were unavailable" in results[2].message
