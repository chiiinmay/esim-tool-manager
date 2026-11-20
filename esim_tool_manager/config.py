"""esim_tool_manager.config
~~~~~~~~~~~~~~~~~~~~~~~~~~
Loads and validates tools.yaml, exposing a typed ToolSpec dataclass
for every tool entry.  The rest of the codebase consumes ToolSpec objects
and never reads raw YAML directly.

Validation rules
----------------
* Required string fields must be non-empty where noted.
* ``kind`` must be ``"system"`` or ``"pip"``.
* Every name in ``depends_on`` must reference another entry in the registry.
* For the **current platform backend** (apt or winget), the tool must have
  a non-empty package name *unless* kind == "pip" (pip tools always use
  ``pip_package``).  Raises ``ConfigError`` with a clear message if not.

Environment overrides
---------------------
Not in scope for Step 1.  Added in a later step.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_REGISTRY: Path = Path(__file__).parent.parent / "tools.yaml"
VALID_KINDS: frozenset[str] = frozenset({"system", "pip"})

# Backend name that the current platform uses.
# platform_detect.py (Step 2) will own this logic properly; here we do the
# minimal check needed so config validation can run on the CI runner.
def _default_backend() -> str:
    if sys.platform.startswith("win"):
        return "winget"
    return "apt"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConfigError(ValueError):
    """Raised when tools.yaml fails validation."""


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolSpec:
    """Typed, validated representation of one entry in tools.yaml."""

    name: str
    display_name: str
    kind: Literal["system", "pip"]
    executable: str
    version_cmd: str
    version_regex: str
    min_version: str
    latest_stable: str
    depends_on: tuple[str, ...]
    pkg_name_apt: str
    pkg_name_winget: str
    pip_package: str
    install_notes: str

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def pkg_name_for(self, backend: str) -> str:
        """Return the package name for *backend* (``apt`` or ``winget``).

        Returns an empty string if the tool has no package for that backend.
        For pip tools this always returns an empty string — use
        :attr:`pip_package` instead.
        """
        mapping = {
            "apt": self.pkg_name_apt,
            "winget": self.pkg_name_winget,
        }
        return mapping.get(backend, "")

    def compiled_version_regex(self) -> re.Pattern[str]:
        """Return a compiled regex for extracting the version string."""
        return re.compile(self.version_regex)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class Registry:
    """Parsed, validated collection of :class:`ToolSpec` objects."""

    def __init__(
        self,
        specs: list[ToolSpec],
        backend: str,
    ) -> None:
        self._specs: dict[str, ToolSpec] = {s.name: s for s in specs}
        self.backend = backend

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def all_tools(self) -> list[ToolSpec]:
        """Return all tools in definition order."""
        return list(self._specs.values())

    def get(self, name: str) -> ToolSpec:
        """Return the :class:`ToolSpec` for *name*, or raise ``KeyError``."""
        try:
            return self._specs[name]
        except KeyError:
            available = ", ".join(sorted(self._specs))
            raise KeyError(
                f"Tool {name!r} not found in registry. "
                f"Available tools: {available}"
            ) from None

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _require_str(raw: dict, key: str, ctx: str) -> str:
    """Return raw[key] as a stripped string, raising ConfigError if missing."""
    val = raw.get(key)
    if val is None:
        raise ConfigError(f"{ctx}: missing required field '{key}'")
    if not isinstance(val, str):
        raise ConfigError(
            f"{ctx}: field '{key}' must be a string, got {type(val).__name__}"
        )
    return val.strip()


def _parse_spec(raw: dict, index: int, backend: str) -> ToolSpec:
    """Parse and validate one raw YAML dict into a :class:`ToolSpec`."""
    ctx = f"tools[{index}]"

    name = _require_str(raw, "name", ctx)
    if not name:
        raise ConfigError(f"{ctx}: 'name' must not be empty")
    ctx = f"tool '{name}'"  # upgrade context to include name

    kind_raw = _require_str(raw, "kind", ctx)
    if kind_raw not in VALID_KINDS:
        raise ConfigError(
            f"{ctx}: 'kind' must be one of {sorted(VALID_KINDS)}, got {kind_raw!r}"
        )
    kind: Literal["system", "pip"] = kind_raw  # type: ignore[assignment]

    executable     = raw.get("executable", "") or ""
    version_cmd    = _require_str(raw, "version_cmd",   ctx)
    version_regex  = _require_str(raw, "version_regex", ctx)
    min_version    = raw.get("min_version",   "") or ""
    latest_stable  = raw.get("latest_stable", "") or ""
    display_name   = raw.get("display_name",  name) or name
    pkg_name_apt   = raw.get("pkg_name_apt",  "") or ""
    pkg_name_winget= raw.get("pkg_name_winget","") or ""
    pip_package    = raw.get("pip_package",   "") or ""
    install_notes  = raw.get("install_notes", "") or ""

    depends_raw = raw.get("depends_on") or []
    if not isinstance(depends_raw, list):
        raise ConfigError(f"{ctx}: 'depends_on' must be a list")
    depends_on = tuple(str(d) for d in depends_raw)

    # Validate regex compiles
    try:
        compiled = re.compile(version_regex)
    except re.error as exc:
        raise ConfigError(
            f"{ctx}: 'version_regex' is not a valid Python regex: {exc}"
        ) from exc
    if compiled.groups != 1:
        raise ConfigError(
            f"{ctx}: 'version_regex' must contain exactly 1 capture group, "
            f"found {compiled.groups}"
        )

    # For system tools, validate a package name exists for the active backend
    if kind == "system":
        pkg_for_backend = {"apt": pkg_name_apt, "winget": pkg_name_winget}.get(
            backend, ""
        )
        if not pkg_for_backend:
            raise ConfigError(
                f"{ctx}: kind='system' but 'pkg_name_{backend}' is empty. "
                f"Add a package name or set kind='pip'."
            )

    # pip tools must have pip_package
    if kind == "pip" and not pip_package:
        raise ConfigError(
            f"{ctx}: kind='pip' but 'pip_package' is empty."
        )

    return ToolSpec(
        name=name,
        display_name=display_name,
        kind=kind,
        executable=str(executable),
        version_cmd=version_cmd,
        version_regex=version_regex,
        min_version=str(min_version),
        latest_stable=str(latest_stable),
        depends_on=depends_on,
        pkg_name_apt=pkg_name_apt,
        pkg_name_winget=pkg_name_winget,
        pip_package=pip_package,
        install_notes=install_notes,
    )


def _validate_depends_on(specs: list[ToolSpec]) -> None:
    """Check that every depends_on name resolves to another entry."""
    names = {s.name for s in specs}
    for spec in specs:
        for dep in spec.depends_on:
            if dep not in names:
                raise ConfigError(
                    f"tool '{spec.name}': depends_on includes '{dep}' "
                    f"which is not defined in tools.yaml"
                )


def load_registry(
    path: Path | str | None = None,
    backend: str | None = None,
) -> Registry:
    """Load *path* (defaults to ``tools.yaml`` next to this package) and
    return a validated :class:`Registry`.

    Parameters
    ----------
    path:
        Path to the YAML file.  Defaults to :data:`DEFAULT_REGISTRY`.
    backend:
        Backend name to validate package names against (``"apt"`` or
        ``"winget"``).  Defaults to the platform default.

    Raises
    ------
    ConfigError
        On any validation failure.
    FileNotFoundError
        If the YAML file does not exist.
    """
    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY
    if not registry_path.exists():
        raise FileNotFoundError(
            f"Registry file not found: {registry_path}"
        )

    if backend is None:
        backend = _default_backend()

    with registry_path.open("r", encoding="utf-8") as fh:
        raw_data = yaml.safe_load(fh)

    if not isinstance(raw_data, dict):
        raise ConfigError("tools.yaml must be a YAML mapping at the top level")

    raw_tools = raw_data.get("tools")
    if not isinstance(raw_tools, list) or len(raw_tools) == 0:
        raise ConfigError("tools.yaml must contain a non-empty 'tools' list")

    specs: list[ToolSpec] = []
    for idx, raw_tool in enumerate(raw_tools):
        if not isinstance(raw_tool, dict):
            raise ConfigError(
                f"tools[{idx}]: each entry must be a YAML mapping, "
                f"got {type(raw_tool).__name__}"
            )
        specs.append(_parse_spec(raw_tool, idx, backend))

    _validate_depends_on(specs)

    return Registry(specs=specs, backend=backend)
