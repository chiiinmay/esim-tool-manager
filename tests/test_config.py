"""tests/test_config.py
~~~~~~~~~~~~~~~~~~~~~
Unit tests for esim_tool_manager.config.

All tests use a minimal in-memory YAML string passed via a tmp_path fixture.
No real tools.yaml is required; no subprocess calls are made.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from esim_tool_manager.config import (
    ConfigError,
    Registry,
    ToolSpec,
    load_registry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(tmp_path: Path, content: str) -> Path:
    """Write *content* to a tools.yaml in *tmp_path* and return the path."""
    p = tmp_path / "tools.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


MINIMAL_SYSTEM = """
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
"""

MINIMAL_PIP = """
    tools:
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

MINIMAL_TWO = """
    tools:
      - name: python3
        display_name: "Python 3"
        kind: system
        version_cmd: "python3 --version"
        version_regex: 'Python (\\d+\\.\\d+\\.\\d+)'
        min_version: "3.10.0"
        latest_stable: ""
        depends_on: []
        pkg_name_apt: python3
        pkg_name_winget: "Python.Python.3.10"
        pip_package: ""
        install_notes: ""
      - name: numpy
        display_name: "NumPy"
        kind: pip
        version_cmd: 'python3 -c "import numpy; print(numpy.__version__)"'
        version_regex: '(\\d+\\.\\d+\\.\\d+)'
        min_version: "1.23.0"
        latest_stable: ""
        depends_on: [python3]
        pkg_name_apt: python3-numpy
        pkg_name_winget: ""
        pip_package: numpy
        install_notes: ""
"""

# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestLoadRegistryHappyPath:

    def test_load_single_system_tool(self, tmp_path):
        p = write_yaml(tmp_path, MINIMAL_SYSTEM)
        reg = load_registry(path=p, backend="apt")
        assert len(reg) == 1
        spec = reg.get("ngspice")
        assert spec.name == "ngspice"
        assert spec.kind == "system"
        assert spec.pkg_name_apt == "ngspice"

    def test_load_single_pip_tool(self, tmp_path):
        p = write_yaml(tmp_path, MINIMAL_PIP)
        reg = load_registry(path=p, backend="apt")
        assert len(reg) == 1
        spec = reg.get("numpy")
        assert spec.kind == "pip"
        assert spec.pip_package == "numpy"

    def test_all_tools_order_preserved(self, tmp_path):
        p = write_yaml(tmp_path, MINIMAL_TWO)
        reg = load_registry(path=p, backend="apt")
        names = [s.name for s in reg.all_tools()]
        assert names == ["python3", "numpy"]

    def test_depends_on_resolved_correctly(self, tmp_path):
        p = write_yaml(tmp_path, MINIMAL_TWO)
        reg = load_registry(path=p, backend="apt")
        numpy_spec = reg.get("numpy")
        assert "python3" in numpy_spec.depends_on

    def test_contains_dunder(self, tmp_path):
        p = write_yaml(tmp_path, MINIMAL_SYSTEM)
        reg = load_registry(path=p, backend="apt")
        assert "ngspice" in reg
        assert "kicad" not in reg

    def test_pkg_name_for_helper(self, tmp_path):
        p = write_yaml(tmp_path, MINIMAL_SYSTEM)
        reg = load_registry(path=p, backend="apt")
        spec = reg.get("ngspice")
        assert spec.pkg_name_for("apt") == "ngspice"
        assert spec.pkg_name_for("winget") == "ngspice.ngspice"
        assert spec.pkg_name_for("unknown") == ""

    def test_compiled_version_regex_works(self, tmp_path):
        p = write_yaml(tmp_path, MINIMAL_SYSTEM)
        reg = load_registry(path=p, backend="apt")
        spec = reg.get("ngspice")
        m = spec.compiled_version_regex().search("ngspice-42 compiled 2024")
        assert m is not None
        assert m.group(1) == "42"

    def test_winget_backend_accepted(self, tmp_path):
        """winget backend: system tools need pkg_name_winget to be set."""
        p = write_yaml(tmp_path, MINIMAL_SYSTEM)
        reg = load_registry(path=p, backend="winget")
        spec = reg.get("ngspice")
        assert spec.pkg_name_for("winget") == "ngspice.ngspice"

    def test_load_real_tools_yaml_apt(self):
        """Smoke-test: the real tools.yaml must load cleanly under apt backend."""
        reg = load_registry(backend="apt")
        expected = {
            "ngspice", "kicad", "ghdl", "verilator",
            "python3", "PyQt5", "matplotlib", "numpy", "scipy", "hdlparse",
        }
        assert expected == {s.name for s in reg.all_tools()}

    def test_missing_optional_fields_use_defaults(self, tmp_path):
        """install_notes and latest_stable default to empty string."""
        yaml_content = """
            tools:
              - name: ngspice
                display_name: "Ngspice"
                kind: system
                version_cmd: "ngspice --version"
                version_regex: 'ngspice-(\\d+)'
                min_version: "37"
                depends_on: []
                pkg_name_apt: ngspice
                pkg_name_winget: "ngspice.ngspice"
                pip_package: ""
        """
        p = write_yaml(tmp_path, yaml_content)
        reg = load_registry(path=p, backend="apt")
        spec = reg.get("ngspice")
        assert spec.install_notes == ""
        assert spec.latest_stable == ""


# ---------------------------------------------------------------------------
# Error-path tests: file / structure
# ---------------------------------------------------------------------------

class TestLoadRegistryErrors:

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Registry file not found"):
            load_registry(path=tmp_path / "missing.yaml")

    def test_top_level_not_a_mapping(self, tmp_path):
        p = write_yaml(tmp_path, "- just a list\n")
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            load_registry(path=p, backend="apt")

    def test_tools_key_missing(self, tmp_path):
        p = write_yaml(tmp_path, "other_key: value\n")
        with pytest.raises(ConfigError, match="non-empty 'tools' list"):
            load_registry(path=p, backend="apt")

    def test_tools_empty_list(self, tmp_path):
        p = write_yaml(tmp_path, "tools: []\n")
        with pytest.raises(ConfigError, match="non-empty 'tools' list"):
            load_registry(path=p, backend="apt")

    def test_tool_entry_not_a_mapping(self, tmp_path):
        p = write_yaml(tmp_path, "tools:\n  - just_a_string\n")
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            load_registry(path=p, backend="apt")


# ---------------------------------------------------------------------------
# Error-path tests: field validation
# ---------------------------------------------------------------------------

class TestFieldValidation:

    def _base(self) -> dict:
        """Return a valid minimal tool dict for mutation testing."""
        return {
            "name": "mytool",
            "display_name": "My Tool",
            "kind": "system",
            "version_cmd": "mytool --version",
            "version_regex": r"mytool (\d+\.\d+)",
            "min_version": "1.0",
            "latest_stable": "",
            "depends_on": [],
            "pkg_name_apt": "mytool",
            "pkg_name_winget": "My.Tool",
            "pip_package": "",
            "install_notes": "",
        }

    def _make_yaml(self, tool_dict: dict) -> str:
        import yaml as _yaml
        return _yaml.dump({"tools": [tool_dict]})

    def test_missing_name_raises(self, tmp_path):
        d = self._base()
        del d["name"]
        p = write_yaml(tmp_path, self._make_yaml(d))
        with pytest.raises(ConfigError, match="missing required field 'name'"):
            load_registry(path=p, backend="apt")

    def test_invalid_kind_raises(self, tmp_path):
        d = self._base()
        d["kind"] = "chocolatey"
        p = write_yaml(tmp_path, self._make_yaml(d))
        with pytest.raises(ConfigError, match="'kind' must be one of"):
            load_registry(path=p, backend="apt")

    def test_bad_regex_raises(self, tmp_path):
        d = self._base()
        d["version_regex"] = r"[unclosed"
        p = write_yaml(tmp_path, self._make_yaml(d))
        with pytest.raises(ConfigError, match="not a valid Python regex"):
            load_registry(path=p, backend="apt")

    def test_regex_zero_groups_raises(self, tmp_path):
        d = self._base()
        d["version_regex"] = r"\d+\.\d+"   # no capture group
        p = write_yaml(tmp_path, self._make_yaml(d))
        with pytest.raises(ConfigError, match="exactly 1 capture group"):
            load_registry(path=p, backend="apt")

    def test_regex_two_groups_raises(self, tmp_path):
        d = self._base()
        d["version_regex"] = r"(\d+)\.(\d+)"
        p = write_yaml(tmp_path, self._make_yaml(d))
        with pytest.raises(ConfigError, match="exactly 1 capture group"):
            load_registry(path=p, backend="apt")

    def test_system_tool_missing_apt_pkg_raises(self, tmp_path):
        d = self._base()
        d["pkg_name_apt"] = ""
        p = write_yaml(tmp_path, self._make_yaml(d))
        with pytest.raises(ConfigError, match="pkg_name_apt.*empty"):
            load_registry(path=p, backend="apt")

    def test_pip_tool_missing_pip_package_raises(self, tmp_path):
        d = self._base()
        d["kind"] = "pip"
        d["pip_package"] = ""
        p = write_yaml(tmp_path, self._make_yaml(d))
        with pytest.raises(ConfigError, match="pip_package.*empty"):
            load_registry(path=p, backend="apt")

    def test_unresolved_depends_on_raises(self, tmp_path):
        d = self._base()
        d["depends_on"] = ["nonexistent_tool"]
        p = write_yaml(tmp_path, self._make_yaml(d))
        with pytest.raises(ConfigError, match="not defined in tools.yaml"):
            load_registry(path=p, backend="apt")

    def test_get_unknown_tool_raises_keyerror(self, tmp_path):
        p = write_yaml(tmp_path, MINIMAL_SYSTEM)
        reg = load_registry(path=p, backend="apt")
        with pytest.raises(KeyError, match="'kicad' not found in registry"):
            reg.get("kicad")

    def test_depends_on_not_a_list_raises(self, tmp_path):
        d = self._base()
        d["depends_on"] = "python3"   # string, not list
        p = write_yaml(tmp_path, self._make_yaml(d))
        with pytest.raises(ConfigError, match="'depends_on' must be a list"):
            load_registry(path=p, backend="apt")


# ---------------------------------------------------------------------------
# ToolSpec is frozen / immutable
# ---------------------------------------------------------------------------

class TestToolSpecImmutability:

    def test_toolspec_is_frozen(self, tmp_path):
        p = write_yaml(tmp_path, MINIMAL_SYSTEM)
        reg = load_registry(path=p, backend="apt")
        spec = reg.get("ngspice")
        with pytest.raises((AttributeError, TypeError)):
            spec.name = "changed"  # type: ignore[misc]
