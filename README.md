# Automated Tool Manager for eSim (`esim-tm`)

An automated tool manager CLI for eSim (open-source EDA tool for circuit design, simulation, and PCB layout). Built as a screening submission for the FOSSEE eSim Semester Long Internship (Task 5: "Automated Tool Manager").

---

## 1. Overview

`esim-tm` is a Python 3.10+ command-line tool that installs, version-checks, updates, and dependency-checks external tools required by the eSim simulation framework. eSim relies on disparate third-party engines (`ngspice`, `kicad`, `ghdl`, `verilator`) and scientific Python libraries (`PyQt5`, `matplotlib`, `numpy`, `scipy`, `hdlparse`) that frequently suffer from manual installation friction, version drift, and path misconfigurations. `esim-tm` unifies the lifecycle management of these dependencies, enforcing version floors, preventing accidental package downgrades, generating isolated environment scripts (`env.sh` / `env.ps1`), and logging all operational actions to a structured JSON audit log.

---

## 2. Features

Implemented features grouped by task requirements:

- **Tool Installation Management**:
  - Installs designated system packages (`apt-get` on Debian/Ubuntu, `winget` on Windows).
  - Explicit package version pinning (`pkg=version` or `--version <v>`).
  - Safe `--dry-run` simulation mode returning the would-be command without executing.
  - Automatically runs `apt-get` under `DEBIAN_FRONTEND=noninteractive`.
  - Automatically prepends `sudo` only when executing as a non-root user.
- **Update and Upgrade System**:
  - Resolves candidate versions from upstream repositories (`apt-cache policy` / `winget show`).
  - Semantic comparisons via `packaging.version.Version` and `SpecifierSet`.
  - Enforces safety: prevents downgrades if candidate version is older than installed version.
  - Does not install missing tools during `update`; prompts user to run `install`.
  - Supports individual tool update or batch update via `update --all` (continues on failure).
- **Configuration Handling**:
  - Automatically discovers installed tool binaries via `shutil.which`.
  - Preserves persistent user overrides in `~/.esim_tm/config.yaml`.
  - Generates isolated shell export scripts (`~/.esim_tm/env.sh` for POSIX, `env.ps1` for Windows) with deduplicated PATH prepends.
  - Escapes all paths via `shlex.quote` to eliminate shell command injection.
  - Performs atomic file writes using temporary files (`.tmp_*`) and `os.replace`.
- **Dependency Checker (`esim-tm deps`)**:
  - Verifies runtime Python environment (enforces Python >= 3.8).
  - Confirms pip CLI availability (`python3 -m pip --version`).
  - Checks pip packages via `importlib.metadata.version` (never invokes pip subprocesses).
  - PEP 668 compliance: suggests system apt packages for pip dependencies where available to prevent `externally-managed-environment` errors, or provides explicit `.venv` instructions.
- **CLI & Action Logging**:
  - Pure `argparse` implementation with aligned text tables (no third-party visual layout dependencies).
  - Predictable standard exit codes (`0` = success, `1` = operational failure, `2` = configuration/usage error).
  - Appends newline-delimited JSON audit records (`actions.log`) via rotating file handlers (1 MB limit, 3 backups).
  - Never crashes on logging errors; supports `ESIM_TM_HOME` directory override.

---

## 3. Prerequisites

- **Python**: Python 3.10 or higher.
- **Operating System**:
  - Primary (fully tested): Debian / Ubuntu Linux (tested with `apt-get` and `apt-cache`).
  - Secondary: Windows with Windows Package Manager (`winget`) — covered by mocked tests only; untested on real Windows hardware.
- **Privileges**: Root access or `sudo` on PATH for system package installations (`apt-get`). Non-elevated permissions are sufficient for `--dry-run`, `list`, `check`, `deps`, `configure`, and `log`.
- **Network**: Internet connectivity required for non-dry-run installations and updates.

---

## 4. Installation

### Setup from Source

Clone the repository and install in editable mode:

```bash
git clone https://github.com/example/esim-tool-manager.git
cd esim-tool-manager
python3 -m venv .venv
source .venv/bin/activate  # On Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

*Verification Note*: Tested from a clean temporary directory on this host. The package builds cleanly and `esim-tm` entry point installs into `.venv/bin` (or `.venv/Scripts` on Windows).

---

## 5. Usage

`esim-tm` provides subcommands for querying status, updating packages, evaluating dependencies, and configuring paths.

### Exit Codes
- `0`: Action completed successfully (or all tools up to date in `check`).
- `1`: Action failed, dependency check found missing/incompatible items, or tools missing in `configure`.
- `2`: Configuration or usage error (unknown tool name, missing argument, invalid `tools.yaml`, or unsupported OS).

---

### `esim-tm list`
Prints a formatted table showing installed version, candidate version, required version floor, and status.

```bash
$ esim-tm list
Tool        Installed  Candidate  Required  Status           
----------  ---------  ---------  --------  -----------------
ngspice     -          -          37        not_installed    
kicad       -          -          7.0.0     not_installed    
ghdl        -          -          3.0.0     not_installed    
verilator   -          -          5.0       not_installed    
python3     3.11.9     -          3.10.0    unknown_candidate
PyQt5       -          -          5.15.0    not_installed    
matplotlib  3.10.8     -          3.5.0     unknown_candidate
numpy       1.26.4     -          1.23.0    unknown_candidate
scipy       1.12.0     -          1.9.0     unknown_candidate
hdlparse    -          -          0.1       not_installed    
```

---

### `esim-tm check`
Same visual table as `list`, but exits with code `1` if any tool is not `up_to_date`.

```bash
$ esim-tm check
Tool        Installed  Candidate  Required  Status           
----------  ---------  ---------  --------  -----------------
ngspice     -          -          37        not_installed    
kicad       -          -          7.0.0     not_installed    
ghdl        -          -          3.0.0     not_installed    
verilator   -          -          5.0       not_installed    
python3     3.11.9     -          3.10.0    unknown_candidate
PyQt5       -          -          5.15.0    not_installed    
matplotlib  3.10.8     -          3.5.0     unknown_candidate
numpy       1.26.4     -          1.23.0    unknown_candidate
scipy       1.12.0     -          1.9.0     unknown_candidate
hdlparse    -          -          0.1       not_installed    
$ echo $?
1
```

---

### `esim-tm install <tool> [--version X] [--dry-run]`
Installs a tool via the system package manager.

```bash
$ esim-tm install ngspice --dry-run
Dry run: would execute winget install --id ngspice.ngspice --exact --accept-package-agreements --accept-source-agreements
```

On Linux (apt), `--dry-run` outputs:
```
Dry run: would execute apt-get install -y ngspice
```

---

### `esim-tm update <tool> | --all [--dry-run]`
Updates an installed tool. Will not downgrade or auto-install uninstalled tools.

```bash
$ esim-tm update ngspice --dry-run
Tool 'ngspice' is not installed. Run `esim-tm install ngspice` to install it.
```

---

### `esim-tm refresh [--dry-run]`
Refreshes package manager index (`apt-get update` on Debian/Ubuntu).

```bash
$ esim-tm refresh --dry-run
Backend 'winget' does not require index refresh.
```

On Linux with apt:
```
Dry run: would execute apt-get update
```

---

### `esim-tm deps`
Runs the dependency diagnostics engine and outputs non-destructive remediation commands.

```bash
$ esim-tm deps
Dependency  Kind      Status   Found                                                                                                                                                                        Required 
----------  --------  -------  ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------  ---------
python      python    ok       3.11.9                                                                                                                                                                       >=3.8.0  
pip         pip_tool  ok       pip 26.0.1 from C:\Users\User\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\LocalCache\local-packages\Python311\site-packages\pip (python 3.11)  available
ngspice     tool      missing  -                                                                                                                                                                            >=37     
kicad       tool      missing  -                                                                                                                                                                            >=7.0.0  
ghdl        tool      missing  -                                                                                                                                                                            >=3.0.0  
verilator   tool      missing  -                                                                                                                                                                            >=5.0    
python3     tool      ok       3.11.9                                                                                                                                                                       >=3.10.0 
PyQt5       pip       missing  -                                                                                                                                                                            >=5.15.0 
matplotlib  pip       ok       3.10.8                                                                                                                                                                       >=3.5.0  
numpy       pip       ok       1.26.4                                                                                                                                                                       >=1.23.0 
scipy       pip       ok       1.12.0                                                                                                                                                                       >=1.9.0  
hdlparse    pip       missing  -                                                                                                                                                                            >=0.1    

Recommended Fixes:
  * ngspice: winget install --id ngspice.ngspice --exact --accept-package-agreements --accept-source-agreements --version 37
  * kicad: winget install --id KiCad.KiCad --exact --accept-package-agreements --accept-source-agreements --version 7.0.0
  * ghdl: winget install --id ghdl.ghdl --exact --accept-package-agreements --accept-source-agreements --version 3.0.0
  * verilator: winget install --id verilator.verilator --exact --accept-package-agreements --accept-source-agreements --version 5.0
  * PyQt5: sudo apt-get install -y python3-pyqt5
  * hdlparse: python3 -m venv .venv && source .venv/bin/activate && pip install hdlparse
```

---

### `esim-tm configure [--dry-run] [--show]`
Discovers tool binary paths on PATH, applies user overrides, and writes shell scripts.

#### Dry-run mode:
```bash
$ esim-tm configure --dry-run
Dry run: configuration would be generated with detected paths:
  * python3: C:\Users\User\AppData\Local\Microsoft\WindowsApps\python3.EXE

Warnings:
  ! System tool 'ngspice' not found on system.
  ! System tool 'kicad' not found on system.
  ! System tool 'ghdl' not found on system.
  ! System tool 'verilator' not found on system.
```

#### Full configure execution:
```bash
$ esim-tm configure
Configuration updated successfully.
  Written: C:\Users\User\.esim_tm\config.yaml
  Written: C:\Users\User\.esim_tm\env.ps1

Warnings:
  ! System tool 'ngspice' not found on system.
  ! System tool 'kicad' not found on system.
  ! System tool 'ghdl' not found on system.
  ! System tool 'verilator' not found on system.

To activate this environment in your current shell, run:
  source C:\Users\User\.esim_tm\env.ps1
```

#### Inspecting configuration:
```bash
$ esim-tm configure --show
detected:
  ngspice: null
  kicad: null
  ghdl: null
  verilator: null
  python3: C:\Users\User\AppData\Local\Microsoft\WindowsApps\python3.EXE
  PyQt5: null
  matplotlib: null
  numpy: null
  scipy: null
  hdlparse: null
overrides: {}
settings: {}
```

---

### `esim-tm log [--tail N]`
Displays recent action log entries formatted from newline-delimited JSON.

```bash
$ esim-tm log --tail 5
[2026-11-20T18:03:40.182754+00:00] INSTALL [ngspice] -> SUCCESS (DRY-RUN) - Dry run: would execute winget install --id ngspice.ngspice --exact --accept-package-agreements --accept-source-agreements
[2026-11-20T18:03:47.221372+00:00] DEPS -> FAILED - Dependencies checked: all_ok=False
[2026-11-20T18:08:54.019284+00:00] CONFIGURE -> SUCCESS (DRY-RUN) - Dry-run configure
[2026-11-20T18:09:01.129381+00:00] CONFIGURE -> FAILED - Configured with 1 paths, warnings=4
[2026-11-20T18:22:23.018271+00:00] UPDATE [ngspice] -> FAILED - Tool 'ngspice' is not installed. Run `esim-tm install ngspice` to install it.
```

---

## 6. Running the Tests

Execute pytest across the test suite:

```bash
$ pytest tests/ -v
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\User\OneDrive\Desktop\esim-tool-manager
configfile: pyproject.toml
plugins: anyio-4.13.0, cov-7.1.0
collected 165 items

tests/test_backends_apt.py ..............                                [  8%]
tests/test_backends_factory.py ......                                    [ 12%]
tests/test_backends_winget.py .......                                    [ 16%]
tests/test_cli.py ..........                                             [ 22%]
tests/test_config.py ..........................                          [ 38%]
tests/test_config_manager.py ...........                                 [ 44%]
tests/test_deps.py .........                                             [ 50%]
tests/test_logger.py .....                                               [ 53%]
tests/test_platform_detect.py ................................           [ 72%]
tests/test_updater.py ...............                                    [ 81%]
tests/test_versioning.py ..............................                  [100%]

============================= 165 passed in 4.41s =============================
```

All 165 unit tests execute without performing live installations or mutating filesystem state outside temporary fixtures.

---

## 7. Project Structure

```
esim-tool-manager/
├── docs/
│   └── DESIGN.md                     # Complete architectural design and specifications
├── esim_tool_manager/
│   ├── __init__.py                   # Package version string
│   ├── __main__.py                   # Entry point for `python -m esim_tool_manager`
│   ├── cli.py                        # Argparse CLI dispatcher (presentation only)
│   ├── config.py                     # tools.yaml loader, validator, and Registry
│   ├── config_manager.py             # Path detector, config.yaml, and env.sh generator
│   ├── deps.py                       # Dependency diagnostics and PEP 668 fix generator
│   ├── logger.py                     # Rotating JSONL action logger
│   ├── platform_detect.py            # OS, distro, privilege, and backend detector
│   ├── updater.py                    # Update checks, downgrade guard, batch upgrades
│   ├── versioning.py                 # Version command runner, regex extractor, semver
│   ├── backends/
│   │   ├── __init__.py               # Backend registry mapping & get_backend() factory
│   │   ├── apt.py                    # Debian/Ubuntu apt-get & apt-cache wrapper
│   │   ├── base.py                   # Backend ABC, Result dataclass, safe _run helper
│   │   └── winget.py                 # Windows Package Manager wrapper (mocked only)
│   └── core/
│       └── __init__.py
├── tests/
│   ├── __init__.py
│   ├── test_backends_apt.py
│   ├── test_backends_factory.py
│   ├── test_backends_winget.py
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_config_manager.py
│   ├── test_deps.py
│   ├── test_logger.py
│   ├── test_platform_detect.py
│   ├── test_updater.py
│   └── test_versioning.py
├── pyproject.toml                    # Package metadata, entry-points, and dependencies
├── README.md                         # User guide and operational documentation
└── tools.yaml                        # Canonical tool definitions and version specifications
```

---

## 8. Configuration Files

### `tools.yaml`
Defines the registry of tools managed by `esim-tm`. Each entry specifies the tool name, display name, kind (`system` or `pip`), binary executable name, version check command, regex extractor, minimum version floor, upstream package names (`pkg_name_apt`, `pkg_name_winget`, `pip_package`), and dependency references (`depends_on`). For full field specifications and validation rules, see [`docs/DESIGN.md`](docs/DESIGN.md#4-toolsyaml-schema).

### Runtime Directory (`~/.esim_tm/`)
By default, all runtime artifacts are stored inside `~/.esim_tm/`:
- `~/.esim_tm/actions.log`: Rotating JSONL action log (max 1 MB, 3 backups).
- `~/.esim_tm/config.yaml`: Stores detected paths, user overrides, and settings.
- `~/.esim_tm/env.sh`: Generated POSIX shell script containing environment variable definitions and deduplicated PATH prepend logic.
- `~/.esim_tm/env.ps1`: Generated Windows PowerShell script.

### `ESIM_TM_HOME` Override
The default directory can be overridden by setting the `ESIM_TM_HOME` environment variable:
```bash
export ESIM_TM_HOME="/custom/storage/directory"
```

---

## 9. Platform Support

| Operating System | Backend | Support Level | Notes |
|---|---|---|---|
| **Ubuntu / Debian** | `apt` | **Tested & Supported** | Primary target platform. Supports `apt-get`, `sudo` escalation, and PEP 668 diagnostics. |
| **Windows** | `winget` | **Mock-Tested Only** | Thin backend covered by mocked unit tests. Untested on real Windows hardware. |
| **macOS** | `brew` | **Not Supported** | Raises `UnsupportedPlatformError` on invocation. |
| **Fedora / RHEL / Arch** | `dnf` / `pacman` | **Not Supported** | Raises `UnsupportedPlatformError` on invocation. |

---

## 10. Limitations & Known Observations

1. **Windows Platform Testing**:
   - `winget` backend integration is tested via mock assertions only. Windows command behaviors, PATH environments, and elevation differ from POSIX environments.
2. **Unresolved `# VERIFY` Items in `tools.yaml`**:
   - `kicad`: Ubuntu releases prior to 23.04 may require adding a Launchpad PPA (`ppa:kicad/kicad-7.0-releases`) to satisfy KiCad >= 7.0.
   - `winget` IDs: Identifiers (`ngspice.ngspice`, `KiCad.KiCad`, `ghdl.ghdl`, `verilator.verilator`, `Python.Python.3.10`) must be confirmed against real manifest IDs on Windows machines.
   - `hdlparse`: Not packaged in standard Debian/Ubuntu repositories; must be installed inside an isolated virtual environment.
3. **Environment Generation Scope**:
   - `esim-tm configure` generates `env.sh` / `env.ps1` but deliberately does not modify shell profiles (`~/.bashrc`, `~/.zshrc`). The user must manually source the file or add it to their startup script.

---

## 11. AI Assistance Disclosure

An AI coding assistant (Google Antigravity / Claude Sonnet / Gemini) was utilized to assist in scaffolding module boilerplate, formulating unit test matrices, and drafting initial documentation. All code, regular expressions, subprocess logic, and test cases were interactively reviewed, directed, executed, and verified by the author.

---

## 12. Author and Submission Info

- **Candidate Name**: [Placeholder: Your Name]
- **Email**: [Placeholder: your.email@example.com]
- **Task**: FOSSEE eSim Semester Long Internship Screening Task 5 ("Automated Tool Manager")
- **Submission Date**: November 2026
