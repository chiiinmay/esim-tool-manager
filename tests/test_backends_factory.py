"""tests/test_backends_factory.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the backend factory get_backend().
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from esim_tool_manager.backends import BACKENDS, AptBackend, WingetBackend, get_backend
from esim_tool_manager.platform_detect import UnsupportedPlatformError

DETECT_BACKEND = "esim_tool_manager.backends.detect_backend"


class TestBackendFactory:

    def test_registry_contains_apt_and_winget(self):
        assert "apt" in BACKENDS
        assert "winget" in BACKENDS
        assert BACKENDS["apt"] is AptBackend
        assert BACKENDS["winget"] is WingetBackend

    def test_get_backend_explicit_apt(self):
        backend = get_backend("apt")
        assert isinstance(backend, AptBackend)

    def test_get_backend_explicit_winget(self):
        backend = get_backend("winget")
        assert isinstance(backend, WingetBackend)

    def test_get_backend_detected_apt(self):
        with patch(DETECT_BACKEND, return_value="apt"):
            backend = get_backend()
            assert isinstance(backend, AptBackend)

    def test_get_backend_detected_winget(self):
        with patch(DETECT_BACKEND, return_value="winget"):
            backend = get_backend()
            assert isinstance(backend, WingetBackend)

    def test_get_backend_unsupported_or_none_raises(self):
        with patch(DETECT_BACKEND, return_value=None):
            with pytest.raises(UnsupportedPlatformError, match="No supported backend available"):
                get_backend()

        with pytest.raises(UnsupportedPlatformError, match="No supported backend available"):
            get_backend("unknown_backend")
