"""
Unit tests for configuration loader and logging setup.
"""

import json
import logging
import os
import tempfile

from core.config import DEFAULT_CONFIG, load_config, setup_logging


def test_load_config_defaults_when_missing() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent_path = os.path.join(tmpdir, "missing_config.json")
        cfg = load_config(non_existent_path)
        assert cfg["hotkey_enabled"] is False
        assert cfg["hotkey"] == "ctrl+alt+h"
        assert cfg["app_name"] == "HP Assistant"
        assert os.path.exists(non_existent_path)


def test_load_config_custom_values() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = os.path.join(tmpdir, "test_config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"hotkey_enabled": True, "hotkey": "ctrl+shift+a"}, f)

        cfg = load_config(cfg_path)
        assert cfg["hotkey_enabled"] is True
        assert cfg["hotkey"] == "ctrl+shift+a"
        assert cfg["app_name"] == "HP Assistant"
        assert cfg["beep_on_toggle"] is True


def test_load_config_corrupted_json() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        corrupted_path = os.path.join(tmpdir, "corrupt.json")
        with open(corrupted_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json")

        cfg = load_config(corrupted_path)
        assert cfg == DEFAULT_CONFIG


def test_setup_logging() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "test.log")
        cfg = {"log_file": log_file, "log_level": "DEBUG"}
        logger = setup_logging(cfg)
        assert logger.name == "HP_Assistant"
        assert os.path.exists(os.path.dirname(log_file))

        # Close all handlers to release Windows file lock before directory cleanup
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
