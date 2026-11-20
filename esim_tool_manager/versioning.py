"""esim_tool_manager.versioning
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runs each tool's ``version_cmd``, extracts the version string with the
tool's own regex, and compares it against the minimum requirement.

Public API
----------
- normalize_version(raw)              -> str
- get_installed_version(tool)         -> VersionResult
- compare(installed, min_version)     -> "ok" | "below_minimum"

Design notes
------------
* ``version_cmd`` is stored as a shell-style string in ``tools.yaml``
  (e.g. ``python3 -c "import PyQt5; print(...)"``) and is split with
  :func:`shlex.split` before being passed to :func:`subprocess.run` with
  ``shell=False`` to avoid shell-injection risks.
* Both ``stdout`` and ``stderr`` are captured because some tools (e.g.
  ``ghdl``) write their version to ``stderr``.  The combined text
  ``stdout + "\\n" + stderr`` is searched for the regex match.
* :class:`packaging.version.InvalidVersion` is caught and mapped to
  ``status="unparsable"`` so a bad version string never crashes the CLI.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Literal

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from esim_tool_manager.config import ToolSpec


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VersionResult:
    """Result of querying an installed version.

    Attributes
    ----------
    status:
        ``"installed"``     — version found and parsed successfully.
        ``"not_installed"`` — command not found (FileNotFoundError) or
                              non-zero exit with no parseable output.
        ``"unparsable"``    — command ran but output did not match the
                              regex, or :class:`packaging.version.Version`
                              raised :class:`~packaging.version.InvalidVersion`.
        ``"timeout"``       — command exceeded the 10 s timeout.
    raw_output:
        Combined stdout + stderr text from the version command.
    version:
        A :class:`packaging.version.Version` instance when
        ``status == "installed"``; ``None`` otherwise.
    """

    status: Literal["installed", "not_installed", "unparsable", "timeout"]
    raw_output: str
    version: Version | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LEADING_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")


def normalize_version(raw: str) -> str:
    """Clean a captured version string so ``packaging.version.Version`` can parse it.

    Handles common real-world variants:

    ============= ==========
    Input         Output
    ============= ==========
    ``"42"``      ``"42"``
    ``"3.0.0"``   ``"3.0.0"``
    ``"5.020"``   ``"5.020"``
    ``"8.0.2-1ubuntu1"`` ``"8.0.2"``
    ``"42+ds-1"`` ``"42"``
    ``"3.0.0-dev"`` ``"3.0.0"``
    ============= ==========

    Strategy:

    1. Split on ``+`` and discard everything after it (Debian local epoch /
       metadata suffix, e.g. ``42+ds-1``).
    2. Extract the leading ``N[.N[.N...]]`` portion with a regex (stops
       before any ``-``, letter suffix, or whitespace).
    3. Return the original string if no numeric sequence is found, so the
       caller can still raise :class:`~packaging.version.InvalidVersion`
       with the meaningful original string.
    """
    # Step 1: strip Debian local-version label (after +)
    s = raw.split("+")[0].strip()
    # Step 2: extract leading numeric version sequence
    m = _LEADING_VERSION_RE.match(s)
    return m.group(1) if m else raw


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

_SUBPROCESS_TIMEOUT = 10  # seconds


def get_installed_version(tool: ToolSpec) -> VersionResult:
    """Query the installed version of *tool*.

    Runs ``tool.version_cmd`` as a subprocess (no shell) with a 10 s timeout.
    Searches combined stdout + stderr for ``tool.version_regex``, then
    normalises and parses the captured group with
    :class:`packaging.version.Version`.

    Parameters
    ----------
    tool:
        A validated :class:`~esim_tool_manager.config.ToolSpec` from the
        registry.

    Returns
    -------
    VersionResult
        Always returns a result; never raises.
    """
    cmd = shlex.split(tool.version_cmd)
    pattern = tool.compiled_version_regex()

    # --- run the command ---------------------------------------------------
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except FileNotFoundError:
        return VersionResult(
            status="not_installed",
            raw_output="",
            version=None,
        )
    except subprocess.TimeoutExpired:
        return VersionResult(
            status="timeout",
            raw_output="",
            version=None,
        )

    combined = proc.stdout + "\n" + proc.stderr
    raw_output = combined.strip()

    # --- search for version ------------------------------------------------
    match = pattern.search(combined)

    if match is None:
        # Non-zero exit with no version string → tool probably not usable
        status: Literal["not_installed", "unparsable"] = (
            "not_installed" if proc.returncode != 0 else "unparsable"
        )
        return VersionResult(status=status, raw_output=raw_output, version=None)

    captured = match.group(1)
    normalised = normalize_version(captured)

    try:
        ver = Version(normalised)
    except InvalidVersion:
        return VersionResult(
            status="unparsable",
            raw_output=raw_output,
            version=None,
        )

    return VersionResult(status="installed", raw_output=raw_output, version=ver)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare(
    installed: Version,
    min_version: str,
) -> Literal["ok", "below_minimum"]:
    """Compare *installed* against *min_version*.

    Parameters
    ----------
    installed:
        The parsed :class:`packaging.version.Version` returned in a
        :class:`VersionResult`.
    min_version:
        The ``min_version`` string from :class:`~esim_tool_manager.config.ToolSpec`.
        An empty string means "no minimum" and always returns ``"ok"``.

    Returns
    -------
    ``"ok"`` or ``"below_minimum"``.
    """
    if not min_version:
        return "ok"

    spec = SpecifierSet(f">={min_version}")
    return "ok" if installed in spec else "below_minimum"
