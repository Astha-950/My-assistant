"""
HP Assistant - Stage 1 Entry Point
Desktop Assistant Skeleton & Master Controller
"""

import logging
import os
import signal
import sys
from typing import Optional

from core.config import load_config, setup_logging
from core.controller import AssistantController, DummyModule
from core.tray import TrayApp


def main() -> None:
    # 1. Load configuration
    config = load_config()

    # 2. Setup logging (logs/ folder, ignored by git)
    logger = setup_logging(config)
    logger.info("==========================================")
    logger.info("Starting HP Assistant (Stage 1)")
    logger.info("Version: %s", config.get("version", "1.0.0"))
    logger.info("Default State: OFF")
    logger.info("==========================================")

    # 3. Initialize Controller (starts OFF by default)
    controller = AssistantController(logger=logger)

    # 4. Register dummy test module to prove start/stop lifecycle
    dummy = DummyModule("VerificationDummyModule")
    controller.register_module(dummy)
    logger.info("Dummy module '%s' registered with controller", dummy.name)

    # 5. Hotkey management
    hotkey_enabled = config.get("hotkey_enabled", False)
    hotkey_str = config.get("hotkey", "ctrl+alt+h")
    hotkey_registered = False

    def cleanup() -> None:
        """Cleanup hooks on shutdown."""
        nonlocal hotkey_registered
        if hotkey_registered:
            try:
                import keyboard
                keyboard.unhook_all()
                logger.info("Keyboard hooks unhooked.")
            except Exception as e:
                logger.debug("Error unhooking keyboard: %s", e)
            hotkey_registered = False

    if hotkey_enabled:
        try:
            import keyboard
            keyboard.add_hotkey(hotkey_str, controller.toggle)
            hotkey_registered = True
            logger.info("Optional global hotkey '%s' enabled and registered.", hotkey_str)
        except Exception as e:
            logger.error("Failed to register global hotkey '%s': %s", hotkey_str, e)
    else:
        logger.info(
            "Global hotkey is disabled in config ('hotkey_enabled': false). "
            "Zero keyboard or mouse hooks installed."
        )

    # 6. Initialize Tray Application
    tray = TrayApp(
        controller=controller,
        config=config,
        cleanup_callback=cleanup,
        logger=logger,
    )

    # Handle standard termination signals gracefully
    def handle_signal(sig: int, frame: Optional[object]) -> None:
        logger.info("Termination signal received (%s). Exiting cleanly...", sig)
        try:
            controller.turn_off()
        except Exception:
            pass
        cleanup()
        tray.stop()
        os._exit(0)

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except (ValueError, AttributeError):
        pass

    logger.info("HP Assistant running in system tray. Right-click tray icon to manage.")

    # 7. Start tray icon (blocks until quit)
    try:
        tray.run()
    except Exception as e:
        logger.error("Unexpected error in system tray loop: %s", e, exc_info=True)
    finally:
        try:
            controller.turn_off()
        except Exception:
            pass
        cleanup()


if __name__ == "__main__":
    main()
