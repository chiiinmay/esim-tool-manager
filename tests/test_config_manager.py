"""tests/test_config_manager.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for esim_tool_manager.config_manager.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from esim_tool_manager.config import load_registry
from esim_tool_manager.config_manager import (
    ConfigResult,
    configure,
    detect_tool_paths,
    generate_env_file,
    get_config_file,
    get_env_file,
    show_config,
)

MINI_YAML = """
tools:
  - name: ngspice
    display_name: "Ngspice"
    kind: system
    executable: ngspice
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
    executable: kicad
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


@pytest.fixture(autouse=True)
def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ESIM_TM_HOME", str(tmp_path / ".esim_tm"))


def _make_reg(tmp_path):
    p = tmp_path / "tools.yaml"
    p.write_text(MINI_YAML, encoding="utf-8")
    return load_registry(path=p, backend="apt")


class TestConfigManager:

    def test_show_config_before_configure(self):
        msg = show_config()
        assert "not been generated yet" in msg

    def test_all_tools_detected_and_files_written(self, tmp_path):
        reg = _make_reg(tmp_path)

        def fake_which(cmd):
            if cmd == "ngspice":
                return "/usr/bin/ngspice"
            if cmd == "kicad":
                return "/usr/bin/kicad"
            return None

        with patch("esim_tool_manager.config_manager.shutil.which", side_effect=fake_which), \
             patch("esim_tool_manager.config_manager.detect_os", return_value="linux"):
            res = configure(reg, dry_run=False)

            assert len(res.warnings) == 0
            assert res.resolved_paths["ngspice"] == str(Path("/usr/bin/ngspice").resolve())
            assert res.resolved_paths["kicad"] == str(Path("/usr/bin/kicad").resolve())
            assert len(res.files_written) == 2

            config_file = get_config_file()
            assert config_file.is_file()
            env_file = get_env_file()
            assert env_file.is_file()

            # Ensure env.sh contains proper exports
            env_content = env_file.read_text(encoding="utf-8")
            assert "ESIM_TM_NGSPICE_PATH=" in env_content
            assert "ESIM_TM_KICAD_PATH=" in env_content

    def test_dry_run_writes_nothing(self, tmp_path):
        reg = _make_reg(tmp_path)
        with patch("esim_tool_manager.config_manager.shutil.which", return_value="/usr/bin/tool"), \
             patch("esim_tool_manager.config_manager.detect_os", return_value="linux"):
            res = configure(reg, dry_run=True)
            assert res.dry_run is True
            assert len(res.files_written) == 0
            assert not get_config_file().exists()
            assert not get_env_file().exists()

    def test_override_beats_detected(self, tmp_path):
        reg = _make_reg(tmp_path)

        # Create custom override binary on disk
        custom_bin = tmp_path / "custom_ngspice"
        custom_bin.write_text("#!/bin/sh\n", encoding="utf-8")

        config_file = get_config_file()
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            yaml.safe_dump({"overrides": {"ngspice": str(custom_bin)}}),
            encoding="utf-8",
        )

        with patch("esim_tool_manager.config_manager.shutil.which", return_value="/usr/bin/ngspice"), \
             patch("esim_tool_manager.config_manager.detect_os", return_value="linux"):
            res = configure(reg, dry_run=False)
            assert res.resolved_paths["ngspice"] == str(custom_bin.resolve())

    def test_invalid_override_ignored_with_warning(self, tmp_path):
        reg = _make_reg(tmp_path)

        config_file = get_config_file()
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            yaml.safe_dump({"overrides": {"ngspice": "/nonexistent/path/ngspice"}}),
            encoding="utf-8",
        )

        with patch("esim_tool_manager.config_manager.shutil.which", return_value="/usr/bin/ngspice"), \
             patch("esim_tool_manager.config_manager.detect_os", return_value="linux"):
            res = configure(reg, dry_run=False)
            assert any("does not exist" in w for w in res.warnings)
            # Falls back to detected path
            assert res.resolved_paths["ngspice"] == str(Path("/usr/bin/ngspice").resolve())

    def test_overrides_preserved_across_runs(self, tmp_path):
        reg = _make_reg(tmp_path)
        custom_bin = tmp_path / "my_kicad"
        custom_bin.write_text("#!/bin/sh\n", encoding="utf-8")

        config_file = get_config_file()
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            yaml.safe_dump({
                "detected": {},
                "overrides": {"kicad": str(custom_bin)},
                "settings": {"custom_flag": True},
            }),
            encoding="utf-8",
        )

        with patch("esim_tool_manager.config_manager.shutil.which", return_value=None), \
             patch("esim_tool_manager.config_manager.detect_os", return_value="linux"):
            configure(reg, dry_run=False)

            with config_file.open("r", encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh)
            assert loaded["overrides"] == {"kicad": str(custom_bin)}
            assert loaded["settings"] == {"custom_flag": True}

    def test_path_with_spaces_and_injection_safely_quoted(self):
        paths = {
            "ngspice": "/opt/tools with spaces/bin/ngspice",
            "kicad": "/bin/$(rm -rf /)/kicad",
        }
        with patch("esim_tool_manager.config_manager.detect_os", return_value="linux"):
            script = generate_env_file(paths)
            assert "'/opt/tools with spaces/bin/ngspice'" in script
            assert "'/bin/$(rm -rf /)/kicad'" in script
            # Ensure literal $(rm -rf /) cannot be executed as subshell
            assert "/bin/$(rm" not in script or "'/bin/$(rm -rf /)/kicad'" in script

    def test_path_entries_deduplicated(self):
        paths = {
            "ngspice": "/opt/esim/bin/ngspice",
            "kicad": "/opt/esim/bin/kicad",
        }
        with patch("esim_tool_manager.config_manager.detect_os", return_value="linux"):
            script = generate_env_file(paths)
            # /opt/esim/bin should only appear once in the prepend list
            assert script.count('export PATH=/opt/esim/bin:"$PATH"') == 1

    def test_atomic_write_leaves_no_temp_file(self, tmp_path):
        reg = _make_reg(tmp_path)
        with patch("esim_tool_manager.config_manager.shutil.which", return_value="/bin/tool"), \
             patch("esim_tool_manager.config_manager.detect_os", return_value="linux"):
            configure(reg, dry_run=False)

            log_dir = get_config_file().parent
            temp_files = list(log_dir.glob(".tmp_*"))
            assert len(temp_files) == 0

    def test_corrupt_config_raises_clear_error(self, tmp_path):
        reg = _make_reg(tmp_path)
        config_file = get_config_file()
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("invalid: yaml: [unclosed", encoding="utf-8")

        with pytest.raises(ValueError, match="Corrupt config file"):
            configure(reg, dry_run=False)

    def test_nothing_outside_home_is_touched(self, tmp_path, monkeypatch):
        home_dir = tmp_path / "sandbox_home"
        monkeypatch.setenv("ESIM_TM_HOME", str(home_dir))

        reg = _make_reg(tmp_path)
        with patch("esim_tool_manager.config_manager.shutil.which", return_value="/bin/tool"), \
             patch("esim_tool_manager.config_manager.detect_os", return_value="linux"):
            res = configure(reg, dry_run=False)
            for f in res.files_written:
                assert Path(f).is_relative_to(home_dir)
