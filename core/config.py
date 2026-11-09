"""
Configuration and logging management for HP Assistant.
"""

import json
import logging
import os
import sys
from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "app_name": "HP Assistant",
    "version": "1.5.0",
    "hotkey_enabled": False,
    "hotkey": "ctrl+alt+h",
    "beep_on_toggle": True,
    "toast_on_toggle": True,
    "log_file": "logs/assistant.log",
    "log_level": "INFO",
    "permissions": {
        "confirmation_timeout_seconds": 10,
        "audit_log_file": "logs/audit.log",
        "safe": [
            "volume",
            "scroll",
            "screenshot",
            "open_app",
            "media_play_pause",
            "window_switch",
            "cursor_move",
            "click",
        ],
        "confirm": [
            "close_window",
            "shutdown",
            "restart",
            "delete_file",
            "type_text",
            "run_command",
            "send_message",
            "cut",
            "drag_drop",
        ],
        "blocked": [
            "format_drive",
            "registry_edit",
            "disable_security",
            "install_software",
        ],
    },
}


def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """
    Safely load configuration from a JSON file.
    Falls back to DEFAULT_CONFIG for any missing keys or if the file cannot be parsed.
    """
    config: Dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))

    if not os.path.exists(config_path):
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
        except OSError:
            pass
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
            if isinstance(user_config, dict):
                # Deep merge top-level keys
                for key, val in user_config.items():
                    if key == "permissions" and isinstance(val, dict):
                        config["permissions"].update(val)
                    else:
                        config[key] = val
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Failed to load config from {config_path} ({e}). Using defaults.", file=sys.stderr)

    return config


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """
    Configure application logging to both a file (logs/) and standard output.
    Logs every event with a precise timestamp.
    """
    log_file = config.get("log_file", "logs/assistant.log")
    log_level_name = config.get("log_level", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("HP_Assistant")
    logger.setLevel(log_level)

    # Avoid adding duplicate handlers if setup_logging is called multiple times
    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # File Handler
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as e:
            print(f"Warning: Could not create file handler for {log_file}: {e}", file=sys.stderr)

        # Stream Handler (stdout)
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(log_level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger
