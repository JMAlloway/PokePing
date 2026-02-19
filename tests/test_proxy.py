"""Tests for proxy rotation."""

import time
from unittest.mock import patch

import pytest

from pokeping.utils.proxy import ProxyRotator, _mask_proxy


class TestProxyRotator:
    def test_no_proxies_returns_none(self):
        rotator = ProxyRotator([])
        assert rotator.next() is None
        assert not rotator.has_proxies

    def test_single_proxy(self):
        rotator = ProxyRotator(["http://proxy1:8080"])
        assert rotator.has_proxies
        assert rotator.next() == "http://proxy1:8080"
        assert rotator.next() == "http://proxy1:8080"

    def test_round_robin(self):
        proxies = ["http://p1:8080", "http://p2:8080", "http://p3:8080"]
        rotator = ProxyRotator(proxies)
        results = [rotator.next() for _ in range(6)]
        assert results == ["http://p1:8080", "http://p2:8080", "http://p3:8080",
                           "http://p1:8080", "http://p2:8080", "http://p3:8080"]

    def test_mark_dead_skips_proxy(self):
        proxies = ["http://p1:8080", "http://p2:8080"]
        rotator = ProxyRotator(proxies)
        rotator.mark_dead("http://p1:8080")
        # Should skip p1 and return p2
        assert rotator.next() == "http://p2:8080"
        assert rotator.next() == "http://p2:8080"

    def test_all_dead_returns_none(self):
        proxies = ["http://p1:8080", "http://p2:8080"]
        rotator = ProxyRotator(proxies)
        rotator.mark_dead("http://p1:8080")
        rotator.mark_dead("http://p2:8080")
        assert rotator.next() is None

    def test_mark_alive_revives(self):
        proxies = ["http://p1:8080"]
        rotator = ProxyRotator(proxies)
        rotator.mark_dead("http://p1:8080")
        assert rotator.next() is None
        rotator.mark_alive("http://p1:8080")
        assert rotator.next() == "http://p1:8080"

    def test_cooldown_revives_proxy(self):
        proxies = ["http://p1:8080"]
        rotator = ProxyRotator(proxies)
        rotator.COOLDOWN_SECONDS = 0.1
        rotator.mark_dead("http://p1:8080")
        assert rotator.next() is None
        time.sleep(0.15)
        assert rotator.next() == "http://p1:8080"

    def test_active_count(self):
        proxies = ["http://p1:8080", "http://p2:8080", "http://p3:8080"]
        rotator = ProxyRotator(proxies)
        assert rotator.active_count == 3
        rotator.mark_dead("http://p1:8080")
        assert rotator.active_count == 2

    def test_from_config_empty(self):
        rotator = ProxyRotator.from_config({})
        assert not rotator.has_proxies

    def test_from_config_with_list(self):
        config = {"proxy_list": ["http://p1:8080", "http://p2:8080"]}
        rotator = ProxyRotator.from_config(config)
        assert rotator.has_proxies
        assert rotator.active_count == 2

    def test_from_config_env_var(self, monkeypatch):
        monkeypatch.setenv("POKEPING_PROXIES", "http://p1:8080,http://p2:8080")
        rotator = ProxyRotator.from_config({})
        assert rotator.active_count == 2

    def test_from_config_proxy_file(self, tmp_path):
        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("http://p1:8080\nhttp://p2:8080\n# comment\n\n")
        config = {"proxy_file": str(proxy_file)}
        rotator = ProxyRotator.from_config(config)
        assert rotator.active_count == 2


class TestMaskProxy:
    def test_no_credentials(self):
        assert _mask_proxy("http://proxy:8080") == "http://proxy:8080"

    def test_with_credentials(self):
        assert _mask_proxy("http://user:pass@proxy:8080") == "http://***@proxy:8080"

    def test_socks5(self):
        assert _mask_proxy("socks5://user:pass@proxy:1080") == "socks5://***@proxy:1080"
