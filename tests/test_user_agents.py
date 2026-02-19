"""Tests for user-agent rotation."""

from pokeping.utils.user_agents import RandomUserAgent


class TestRandomUserAgent:
    def test_get_returns_string(self):
        ua = RandomUserAgent()
        result = ua.get()
        assert isinstance(result, str)
        assert "Mozilla" in result

    def test_get_headers_has_required_keys(self):
        ua = RandomUserAgent()
        headers = ua.get_headers()
        assert "User-Agent" in headers
        assert "Accept-Language" in headers
        assert "Accept-Encoding" in headers
        assert "Connection" in headers

    def test_rotation_varies(self):
        ua = RandomUserAgent()
        # With 14 UAs, getting 100 should produce at least 2 distinct values
        agents = {ua.get() for _ in range(100)}
        assert len(agents) > 1

    def test_custom_pool(self):
        custom = ["CustomAgent/1.0", "CustomAgent/2.0"]
        ua = RandomUserAgent(custom)
        result = ua.get()
        assert result in custom

    def test_chrome_ua_has_sec_ch_ua(self):
        # Force a Chrome UA
        ua = RandomUserAgent(["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"])
        headers = ua.get_headers()
        assert "Sec-CH-UA" in headers
        assert headers["Sec-CH-UA-Platform"] == '"Windows"'
