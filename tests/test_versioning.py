"""tests/test_versioning.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for esim_tool_manager.versioning.

subprocess.run is always mocked — no real commands are executed.
ToolSpec objects are built from a minimal in-memory YAML so we
exercise the real ToolSpec.compiled_version_regex() path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from packaging.version import Version

from esim_tool_manager.config import load_registry
from esim_tool_manager.versioning import (
    VersionResult,
    compare,
    get_installed_version,
    normalize_version,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SUBPROCESS_RUN_PATH = "esim_tool_manager.versioning.subprocess.run"


def _make_tool(tmp_path: Path, **overrides):
    """Build a minimal ToolSpec from a YAML written to tmp_path."""
    defaults = {
        "name": "mytool",
        "display_name": "My Tool",
        "kind": "system",
        "version_cmd": "mytool --version",
        "version_regex": r"mytool (\d+\.\d+\.\d+)",
        "min_version": "1.0.0",
        "latest_stable": "",
        "depends_on": [],
        "pkg_name_apt": "mytool",
        "pkg_name_winget": "My.Tool",
        "pip_package": "",
        "install_notes": "",
    }
    defaults.update(overrides)
    import yaml
    yaml_text = yaml.dump({"tools": [defaults]})
    p = tmp_path / "tools.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    reg = load_registry(path=p, backend="apt")
    return reg.get("mytool")


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Return a mock CompletedProcess."""
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


# ---------------------------------------------------------------------------
# normalize_version
# ---------------------------------------------------------------------------

class TestNormalizeVersion:

    def test_clean_semver_unchanged(self):
        assert normalize_version("3.0.0") == "3.0.0"

    def test_single_integer(self):
        assert normalize_version("42") == "42"

    def test_leading_zero_minor(self):
        """'5.020' is valid semver — should not be mangled."""
        assert normalize_version("5.020") == "5.020"

    def test_debian_revision_stripped(self):
        # "8.0.2-1ubuntu1" captured if regex is loose
        assert normalize_version("8.0.2-1ubuntu1") == "8.0.2"

    def test_epoch_plus_suffix_stripped(self):
        # "42+ds-1" Debian epoch-style local label
        assert normalize_version("42+ds-1") == "42"

    def test_dev_suffix_stripped(self):
        assert normalize_version("3.0.0-dev") == "3.0.0"

    def test_rc_suffix_stripped(self):
        assert normalize_version("5.1.0-rc1") == "5.1.0"

    def test_no_leading_digits_returned_raw(self):
        """If there are no digits at all, return raw so caller can raise."""
        assert normalize_version("unknown") == "unknown"

    def test_two_part_version(self):
        assert normalize_version("5.0") == "5.0"


# ---------------------------------------------------------------------------
# get_installed_version
# ---------------------------------------------------------------------------

class TestGetInstalledVersion:

    # --- installed: version in stdout ---

    def test_installed_version_in_stdout(self, tmp_path):
        tool = _make_tool(
            tmp_path,
            version_cmd="ngspice --version",
            version_regex=r"ngspice-(\d+)",
        )
        with patch(SUBPROCESS_RUN_PATH, return_value=_proc(stdout="ngspice-42")):
            result = get_installed_version(tool)

        assert result.status == "installed"
        assert result.version == Version("42")
        assert "ngspice-42" in result.raw_output

    # --- installed: version in stderr ---

    def test_installed_version_in_stderr(self, tmp_path):
        """Some tools (e.g. ghdl) print the version to stderr."""
        tool = _make_tool(
            tmp_path,
            version_cmd="ghdl --version",
            version_regex=r"GHDL (\d+\.\d+\.\d+)",
        )
        with patch(
            SUBPROCESS_RUN_PATH,
            return_value=_proc(stdout="", stderr="GHDL 3.0.0 (v3.0.0)"),
        ):
            result = get_installed_version(tool)

        assert result.status == "installed"
        assert result.version == Version("3.0.0")

    # --- installed: Debian version suffix normalised ---

    def test_installed_debian_suffix_normalised(self, tmp_path):
        tool = _make_tool(
            tmp_path,
            version_cmd="kicad --version",
            version_regex=r"(\d+\.\d+\.\d+)",
        )
        with patch(
            SUBPROCESS_RUN_PATH,
            return_value=_proc(stdout="KiCad 7.0.11-1ubuntu1"),
        ):
            result = get_installed_version(tool)

        assert result.status == "installed"
        assert result.version == Version("7.0.11")

    # --- installed: version in stdout with non-zero returncode still found ---

    def test_non_zero_returncode_but_version_found(self, tmp_path):
        """Some tools exit non-zero for --version; we still parse the output."""
        tool = _make_tool(
            tmp_path,
            version_cmd="mytool --version",
            version_regex=r"mytool (\d+\.\d+\.\d+)",
        )
        with patch(
            SUBPROCESS_RUN_PATH,
            return_value=_proc(stdout="mytool 2.0.0", returncode=1),
        ):
            result = get_installed_version(tool)

        assert result.status == "installed"
        assert result.version == Version("2.0.0")

    # --- not_installed: FileNotFoundError ---

    def test_not_installed_file_not_found(self, tmp_path):
        tool = _make_tool(tmp_path)
        with patch(SUBPROCESS_RUN_PATH, side_effect=FileNotFoundError):
            result = get_installed_version(tool)

        assert result.status == "not_installed"
        assert result.version is None
        assert result.raw_output == ""

    # --- not_installed: non-zero returncode and no match ---

    def test_not_installed_nonzero_no_match(self, tmp_path):
        tool = _make_tool(tmp_path)
        with patch(
            SUBPROCESS_RUN_PATH,
            return_value=_proc(
                stdout="bash: mytool: command not found",
                returncode=127,
            ),
        ):
            result = get_installed_version(tool)

        assert result.status == "not_installed"
        assert result.version is None

    # --- timeout ---

    def test_timeout(self, tmp_path):
        tool = _make_tool(tmp_path)
        with patch(
            SUBPROCESS_RUN_PATH,
            side_effect=subprocess.TimeoutExpired(cmd="mytool --version", timeout=10),
        ):
            result = get_installed_version(tool)

        assert result.status == "timeout"
        assert result.version is None
        assert result.raw_output == ""

    # --- unparsable: garbage output with returncode 0 ---

    def test_unparsable_garbage_output(self, tmp_path):
        tool = _make_tool(tmp_path)
        with patch(
            SUBPROCESS_RUN_PATH,
            return_value=_proc(stdout="Lorem ipsum dolor sit amet", returncode=0),
        ):
            result = get_installed_version(tool)

        assert result.status == "unparsable"
        assert result.version is None

    # --- unparsable: regex matches but packaging raises InvalidVersion ---

    def test_unparsable_invalid_version_string(self, tmp_path):
        """If the regex captures something packaging cannot parse, → unparsable."""
        tool = _make_tool(
            tmp_path,
            version_regex=r"ver=(\S+)",
        )
        with patch(
            SUBPROCESS_RUN_PATH,
            return_value=_proc(stdout="ver=not-a-version-at-all!"),
        ):
            result = get_installed_version(tool)

        assert result.status == "unparsable"
        assert result.version is None

    # --- pip tool: version_cmd with shlex splitting ---

    def test_pip_tool_shlex_split(self, tmp_path):
        """version_cmd like 'python3 -c "import x; print(x.__version__)"'
        must be split correctly by shlex, not on spaces naively."""
        tool = _make_tool(
            tmp_path,
            name="mytool",
            kind="pip",
            version_cmd='python3 -c "import mytool; print(mytool.__version__)"',
            version_regex=r"(\d+\.\d+\.\d+)",
            pkg_name_apt="",
            pkg_name_winget="",
            pip_package="mytool",
        )
        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return _proc(stdout="1.2.3")

        with patch(SUBPROCESS_RUN_PATH, side_effect=fake_run):
            result = get_installed_version(tool)

        assert result.status == "installed"
        assert result.version == Version("1.2.3")
        # shlex should have produced 3 elements: python3, -c, <the expression>
        assert captured_cmd[0] == "python3"
        assert captured_cmd[1] == "-c"
        assert len(captured_cmd) == 3

    # --- ngspice single-integer version ---

    def test_ngspice_integer_version(self, tmp_path):
        tool = _make_tool(
            tmp_path,
            version_cmd="ngspice --version",
            version_regex=r"ngspice-(\d+)",
            min_version="37",
        )
        with patch(
            SUBPROCESS_RUN_PATH,
            return_value=_proc(stdout="** ngspice-42 : Circuit level simulation program"),
        ):
            result = get_installed_version(tool)

        assert result.status == "installed"
        assert result.version == Version("42")

    # --- verilator two-part version ---

    def test_verilator_two_part_version(self, tmp_path):
        tool = _make_tool(
            tmp_path,
            version_cmd="verilator --version",
            version_regex=r"Verilator (\d+\.\d+)",
            min_version="5.0",
        )
        with patch(
            SUBPROCESS_RUN_PATH,
            return_value=_proc(stdout="Verilator 5.020 2024-01-01"),
        ):
            result = get_installed_version(tool)

        assert result.status == "installed"
        assert result.version == Version("5.020")


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

class TestCompare:

    def test_above_minimum_ok(self):
        assert compare(Version("42"), "37") == "ok"

    def test_equal_minimum_ok(self):
        assert compare(Version("37"), "37") == "ok"

    def test_below_minimum(self):
        assert compare(Version("36"), "37") == "below_minimum"

    def test_semver_above_minimum(self):
        assert compare(Version("7.0.11"), "7.0.0") == "ok"

    def test_semver_equal_minimum(self):
        assert compare(Version("5.15.0"), "5.15.0") == "ok"

    def test_semver_below_minimum(self):
        assert compare(Version("5.14.9"), "5.15.0") == "below_minimum"

    def test_empty_min_version_always_ok(self):
        """Empty min_version means 'no minimum required'."""
        assert compare(Version("0.0.1"), "") == "ok"

    def test_minor_version_comparison(self):
        assert compare(Version("1.23.0"), "1.23.0") == "ok"
        assert compare(Version("1.22.9"), "1.23.0") == "below_minimum"

    def test_two_part_version_comparison(self):
        """e.g. verilator 5.020 >= 5.0"""
        assert compare(Version("5.020"), "5.0") == "ok"
        assert compare(Version("4.9"), "5.0") == "below_minimum"
