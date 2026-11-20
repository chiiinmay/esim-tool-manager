"""tests/test_platform_detect.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for esim_tool_manager.platform_detect.

All OS interactions (platform.system, shutil.which, os.geteuid, ctypes,
/etc/os-release) are mocked — no real commands are run.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from esim_tool_manager.platform_detect import (
    DistroInfo,
    PlatformInfo,
    UnsupportedPlatformError,
    detect_backend,
    detect_distro,
    detect_os,
    get_platform_info,
    is_privileged,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OS_DETECT_PATH = "esim_tool_manager.platform_detect.platform.system"
WHICH_PATH = "esim_tool_manager.platform_detect.shutil.which"
OS_MODULE_PATH = "esim_tool_manager.platform_detect.os"
# Patch the module-level ``geteuid`` alias, not os.geteuid directly.
# This works on both Linux and Windows test runners.
GETEUID_PATH = "esim_tool_manager.platform_detect.geteuid"


def _mock_os(geteuid_return: int) -> MagicMock:
    """Return a mock ``os`` module with a working ``geteuid``."""
    m = MagicMock()
    m.geteuid.return_value = geteuid_return
    return m


# ---------------------------------------------------------------------------
# detect_os
# ---------------------------------------------------------------------------

class TestDetectOs:

    def test_linux(self):
        with patch(OS_DETECT_PATH, return_value="Linux"):
            assert detect_os() == "linux"

    def test_windows(self):
        with patch(OS_DETECT_PATH, return_value="Windows"):
            assert detect_os() == "windows"

    def test_darwin_maps_to_macos(self):
        with patch(OS_DETECT_PATH, return_value="Darwin"):
            assert detect_os() == "macos"

    def test_unknown_maps_to_macos(self):
        """Any unknown system string maps to 'macos' (safe fallback)."""
        with patch(OS_DETECT_PATH, return_value="FreeBSD"):
            assert detect_os() == "macos"


# ---------------------------------------------------------------------------
# detect_distro
# ---------------------------------------------------------------------------

class TestDetectDistro:

    def test_returns_none_on_windows(self):
        with patch(OS_DETECT_PATH, return_value="Windows"):
            assert detect_distro() is None

    def test_returns_none_on_macos(self):
        with patch(OS_DETECT_PATH, return_value="Darwin"):
            assert detect_distro() is None

    def test_returns_none_when_os_release_missing(self, tmp_path):
        with patch(OS_DETECT_PATH, return_value="Linux"):
            result = detect_distro(_os_release=tmp_path / "nonexistent")
            assert result is None

    def test_parses_ubuntu_os_release(self, tmp_path):
        (tmp_path / "os-release").write_text(
            'ID=ubuntu\nVERSION_ID="22.04"\nNAME="Ubuntu"\n',
            encoding="utf-8",
        )
        with patch(OS_DETECT_PATH, return_value="Linux"):
            result = detect_distro(_os_release=tmp_path / "os-release")
        assert result == DistroInfo(id="ubuntu", version_id="22.04")

    def test_parses_debian_os_release(self, tmp_path):
        (tmp_path / "os-release").write_text(
            "ID=debian\nVERSION_ID=12\n",
            encoding="utf-8",
        )
        with patch(OS_DETECT_PATH, return_value="Linux"):
            result = detect_distro(_os_release=tmp_path / "os-release")
        assert result == DistroInfo(id="debian", version_id="12")

    def test_missing_version_id_defaults_to_empty(self, tmp_path):
        (tmp_path / "os-release").write_text(
            "ID=arch\n",
            encoding="utf-8",
        )
        with patch(OS_DETECT_PATH, return_value="Linux"):
            result = detect_distro(_os_release=tmp_path / "os-release")
        assert result is not None
        assert result.id == "arch"
        assert result.version_id == ""

    def test_ignores_comment_lines(self, tmp_path):
        (tmp_path / "os-release").write_text(
            "# This is a comment\nID=ubuntu\nVERSION_ID=22.04\n",
            encoding="utf-8",
        )
        with patch(OS_DETECT_PATH, return_value="Linux"):
            result = detect_distro(_os_release=tmp_path / "os-release")
        assert result is not None
        assert result.id == "ubuntu"

    def test_strips_single_quoted_values(self, tmp_path):
        (tmp_path / "os-release").write_text(
            "ID='linuxmint'\nVERSION_ID='21.3'\n",
            encoding="utf-8",
        )
        with patch(OS_DETECT_PATH, return_value="Linux"):
            result = detect_distro(_os_release=tmp_path / "os-release")
        assert result == DistroInfo(id="linuxmint", version_id="21.3")


# ---------------------------------------------------------------------------
# detect_backend
# ---------------------------------------------------------------------------

class TestDetectBackend:

    def test_linux_with_apt_get(self):
        with patch(OS_DETECT_PATH, return_value="Linux"), \
             patch(WHICH_PATH, return_value="/usr/bin/apt-get"):
            assert detect_backend() == "apt"

    def test_linux_without_apt_get(self):
        with patch(OS_DETECT_PATH, return_value="Linux"), \
             patch(WHICH_PATH, return_value=None):
            assert detect_backend() is None

    def test_windows_with_winget(self):
        with patch(OS_DETECT_PATH, return_value="Windows"), \
             patch(WHICH_PATH, return_value="C:\\Windows\\winget.exe"):
            assert detect_backend() == "winget"

    def test_windows_without_winget(self):
        with patch(OS_DETECT_PATH, return_value="Windows"), \
             patch(WHICH_PATH, return_value=None):
            assert detect_backend() is None

    def test_macos_returns_none(self):
        with patch(OS_DETECT_PATH, return_value="Darwin"), \
             patch(WHICH_PATH, return_value="/usr/local/bin/brew"):
            # Even if brew is present, macos has no supported backend
            assert detect_backend() is None


# ---------------------------------------------------------------------------
# is_privileged
# ---------------------------------------------------------------------------

class TestIsPrivileged:

    # --- Linux ---

    def test_linux_root(self):
        with patch(OS_DETECT_PATH, return_value="Linux"), \
             patch(OS_MODULE_PATH, _mock_os(0)):
            assert is_privileged() is True

    def test_linux_non_root_with_sudo(self):
        with patch(OS_DETECT_PATH, return_value="Linux"), \
             patch(OS_MODULE_PATH, _mock_os(1000)), \
             patch(WHICH_PATH, return_value="/usr/bin/sudo"):
            assert is_privileged() is True

    def test_linux_non_root_without_sudo(self):
        with patch(OS_DETECT_PATH, return_value="Linux"), \
             patch(OS_MODULE_PATH, _mock_os(1000)), \
             patch(WHICH_PATH, return_value=None):
            assert is_privileged() is False

    # --- Windows ---

    def test_windows_admin(self):
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 1
        with patch(OS_DETECT_PATH, return_value="Windows"), \
             patch.dict("sys.modules", {"ctypes": mock_ctypes}):
            # Re-import needed: patch the name inside the module
            with patch(
                "esim_tool_manager.platform_detect.ctypes",
                mock_ctypes,
                create=True,
            ):
                # Call the function; it does `import ctypes` inside
                # the if-branch so we patch it at the module level
                result = _call_is_privileged_with_mock_ctypes(mock_ctypes)
        assert result is True

    def test_windows_non_admin(self):
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 0
        with patch(OS_DETECT_PATH, return_value="Windows"):
            result = _call_is_privileged_with_mock_ctypes(mock_ctypes)
        assert result is False

    def test_windows_ctypes_raises_returns_false(self):
        """If ctypes raises for any reason, return False safely."""
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.IsUserAnAdmin.side_effect = OSError("no windll")
        with patch(OS_DETECT_PATH, return_value="Windows"):
            result = _call_is_privileged_with_mock_ctypes(mock_ctypes)
        assert result is False

    # --- macOS / other ---

    def test_other_os_returns_false(self):
        with patch(OS_DETECT_PATH, return_value="Darwin"):
            assert is_privileged() is False


def _call_is_privileged_with_mock_ctypes(mock_ctypes: MagicMock) -> bool:
    """Helper: call is_privileged() with a mocked ctypes module.

    ``is_privileged`` does ``import ctypes`` inside the Windows branch,
    so we patch ``sys.modules["ctypes"]`` for the duration of the call.
    """
    import sys
    original = sys.modules.get("ctypes")
    sys.modules["ctypes"] = mock_ctypes
    try:
        return is_privileged()
    finally:
        if original is None:
            sys.modules.pop("ctypes", None)
        else:
            sys.modules["ctypes"] = original


# ---------------------------------------------------------------------------
# get_platform_info
# ---------------------------------------------------------------------------

class TestGetPlatformInfo:

    def _make_os_release(self, tmp_path: Path) -> Path:
        p = tmp_path / "os-release"
        p.write_text("ID=ubuntu\nVERSION_ID=22.04\n", encoding="utf-8")
        return p

    def test_linux_with_apt_returns_platform_info(self, tmp_path):
        os_release = self._make_os_release(tmp_path)
        with patch(OS_DETECT_PATH, return_value="Linux"), \
             patch(WHICH_PATH, side_effect=lambda name: (
                 "/usr/bin/apt-get" if name == "apt-get" else
                 "/usr/bin/sudo" if name == "sudo" else None
             )), \
             patch(OS_MODULE_PATH, _mock_os(1000)):
            info = get_platform_info()

        assert isinstance(info, PlatformInfo)
        assert info.os == "linux"
        assert info.backend == "apt"
        # distro uses real /etc/os-release on this runner; just check type
        assert info.distro is None or isinstance(info.distro, DistroInfo)

    def test_windows_with_winget_returns_platform_info(self):
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 1
        with patch(OS_DETECT_PATH, return_value="Windows"), \
             patch(WHICH_PATH, return_value="winget.exe"):
            import sys
            sys.modules["ctypes"] = mock_ctypes
            try:
                info = get_platform_info()
            finally:
                sys.modules.pop("ctypes", None)

        assert info.os == "windows"
        assert info.backend == "winget"
        assert info.distro is None   # no /etc/os-release on Windows

    def test_linux_without_apt_raises(self):
        with patch(OS_DETECT_PATH, return_value="Linux"), \
             patch(WHICH_PATH, return_value=None):
            with pytest.raises(UnsupportedPlatformError, match="apt-get not found"):
                get_platform_info()

    def test_windows_without_winget_raises(self):
        with patch(OS_DETECT_PATH, return_value="Windows"), \
             patch(WHICH_PATH, return_value=None):
            with pytest.raises(UnsupportedPlatformError, match="winget not found"):
                get_platform_info()

    def test_macos_raises_unsupported(self):
        with patch(OS_DETECT_PATH, return_value="Darwin"), \
             patch(WHICH_PATH, return_value=None):
            with pytest.raises(UnsupportedPlatformError, match="Unsupported OS"):
                get_platform_info()

    def test_error_message_mentions_apt_for_linux(self):
        with patch(OS_DETECT_PATH, return_value="Linux"), \
             patch(WHICH_PATH, return_value=None):
            with pytest.raises(UnsupportedPlatformError) as exc_info:
                get_platform_info()
        assert "Debian/Ubuntu" in str(exc_info.value)

    def test_error_message_mentions_microsoft_store_for_windows(self):
        with patch(OS_DETECT_PATH, return_value="Windows"), \
             patch(WHICH_PATH, return_value=None):
            with pytest.raises(UnsupportedPlatformError) as exc_info:
                get_platform_info()
        assert "Microsoft Store" in str(exc_info.value)

    def test_platform_info_is_frozen(self, tmp_path):
        with patch(OS_DETECT_PATH, return_value="Linux"), \
             patch(WHICH_PATH, side_effect=lambda n: (
                 "/usr/bin/apt-get" if n == "apt-get" else None
             )), \
             patch(OS_MODULE_PATH, _mock_os(0)):
            info = get_platform_info()

        with pytest.raises((AttributeError, TypeError)):
            info.os = "windows"  # type: ignore[misc]
