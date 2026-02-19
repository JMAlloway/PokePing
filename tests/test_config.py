"""Tests for configuration loading."""

import os
import tempfile

import pytest
import yaml

from pokeping.config import load_config, _deep_merge, _set_nested


class TestDeepMerge:
    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"top": {"a": 1, "b": 2}}
        override = {"top": {"b": 3, "c": 4}}
        result = _deep_merge(base, override)
        assert result == {"top": {"a": 1, "b": 3, "c": 4}}

    def test_override_replaces_non_dict(self):
        base = {"a": {"nested": 1}}
        override = {"a": "flat"}
        result = _deep_merge(base, override)
        assert result == {"a": "flat"}

    def test_base_unchanged(self):
        base = {"a": 1}
        override = {"a": 2}
        _deep_merge(base, override)
        assert base == {"a": 1}


class TestSetNested:
    def test_flat_key(self):
        d = {}
        _set_nested(d, "key", "value")
        assert d == {"key": "value"}

    def test_nested_key(self):
        d = {}
        _set_nested(d, "a.b.c", 42)
        assert d == {"a": {"b": {"c": 42}}}

    def test_existing_nested(self):
        d = {"a": {"existing": 1}}
        _set_nested(d, "a.new", 2)
        assert d == {"a": {"existing": 1, "new": 2}}


class TestLoadConfig:
    def test_load_from_file(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "poll_interval": 30,
            "discord_webhook_url": "https://example.com/webhook",
        }))
        config = load_config(str(config_file))
        assert config["poll_interval"] == 30
        assert config["discord_webhook_url"] == "https://example.com/webhook"

    def test_missing_file_returns_empty(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        assert config == {}

    def test_env_var_override(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "discord_webhook_url": "original",
            "poll_interval": 60,
        }))
        monkeypatch.setenv("POKEPING_DISCORD_WEBHOOK", "from_env")
        monkeypatch.setenv("POKEPING_POLL_INTERVAL", "15")
        config = load_config(str(config_file))
        assert config["discord_webhook_url"] == "from_env"
        assert config["poll_interval"] == 15

    def test_env_var_nested(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"affiliate": {"amazon_tag": ""}}))
        monkeypatch.setenv("POKEPING_AMAZON_TAG", "test-tag-20")
        config = load_config(str(config_file))
        assert config["affiliate"]["amazon_tag"] == "test-tag-20"
