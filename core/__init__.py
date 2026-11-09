"""
Core package for HP Assistant.
"""

from .config import load_config, setup_logging
from .controller import AssistantController, BaseModule, DummyModule
from .permissions import PermissionManager, permissions
from .tray import TrayApp

__all__ = [
    "load_config",
    "setup_logging",
    "AssistantController",
    "BaseModule",
    "DummyModule",
    "PermissionManager",
    "permissions",
    "TrayApp",
]
