"""
HP Assistant - Stage 2.1 Entry Point
Desktop Assistant Skeleton, Master & Per-Feature Toggles, Security Permission Gateway,
and Offline Wake-Phrase & Voice Processing Pipeline.
Includes robust Ctrl+C signal handling, watchdog timeout, and clean process termination.
"""

import logging
import os
import signal
import sys
import threading
import time
from typing import Optional

from core.config import load_config, setup_logging
from core.controller import AssistantController, DummyModule
from core.permissions import permissions
from core.tray import TrayApp
from modules.voice import VoiceModule


def main() -> None:
    # 1. Load configuration
    config = load_config()

    # 2. Setup logging (logs/ folder, ignored by git)
    logger = setup_logging(config)
    logger.info("==========================================")
    logger.info("Starting HP Assistant (Stage 2.1)")
    logger.info("Version: %s", config.get("version", "2.1.0"))
    logger.info("Default State: Master OFF | Voice OFF | Gestures OFF")
    logger.info("==========================================")

    # 3. Initialize Controller (starts OFF by default)
    controller = AssistantController(logger=logger)

    # 4. Register dummy test module to prove start/stop lifecycle
    dummy = DummyModule("VerificationDummyModule")
    controller.register_module(dummy)
    logger.info("Dummy module '%s' registered with controller", dummy.name)

    # 5. Initialize Permissions Gateway
    permissions.reload_config(config)
    logger.info("Permissions gateway loaded. Safe, Confirm, and Blocked tiers active.")

    # 6. Initialize Voice Module and register under feature "voice"
    voice_module = VoiceModule(controller=controller, logger=logger)
    controller.register_module(voice_module, feature="voice")
    logger.info("VoiceModule registered under feature 'voice'.")

    # 7. Hotkey management
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

    # 8. Clean shutdown coordinator with hard-exit fallback
    shutdown_lock = threading.Lock()
    is_shutting_down = False
    stop_event = threading.Event()
    tray: Optional[TrayApp] = None

    def initiate_shutdown(exit_code: int = 0) -> None:
        nonlocal is_shutting_down
        with shutdown_lock:
            if is_shutting_down:
                return
            is_shutting_down = True
            stop_event.set()

        # Watchdog: hard-exit after 5 seconds if graceful cleanup blocks
        def watchdog() -> None:
            time.sleep(5.0)
            logger.warning("Graceful shutdown exceeded 5 seconds. Forcing process exit.")
            os._exit(exit_code)

        threading.Thread(target=watchdog, name="ShutdownWatchdog", daemon=True).start()

        logger.info("Initiating clean application shutdown...")
        try:
            controller.turn_off()
        except Exception as e:
            logger.error("Error stopping controller during shutdown: %s", e)

        cleanup()

        if tray is not None:
            try:
                tray.stop()
            except Exception as e:
                logger.debug("Error stopping tray during shutdown: %s", e)

        logger.info("HP Assistant shutdown complete. Exiting process.")
        os._exit(exit_code)

    # 9. Initialize Tray Application
    tray = TrayApp(
        controller=controller,
        config=config,
        cleanup_callback=lambda: initiate_shutdown(0),
        logger=logger,
    )

    # Signal handlers for SIGINT (Ctrl+C) and SIGTERM
    def handle_signal(sig: int, frame: Optional[object]) -> None:
        logger.info("Termination signal (%s) received.", sig)
        initiate_shutdown(0)

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except (ValueError, AttributeError):
        pass

    logger.info("HP Assistant running. Tray active in background. Press Ctrl+C to stop.")

    # 10. Start tray detached so the main thread processes signals
    try:
        tray.run_detached()
    except Exception as e:
        logger.error("Error starting detached system tray: %s", e)
        initiate_shutdown(1)

    # 11. Main thread loop waits in short intervals so Ctrl+C is caught promptly
    try:
        while not stop_event.is_set():
            stop_event.wait(0.5)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt (Ctrl+C) caught on main thread.")
        initiate_shutdown(0)


if __name__ == "__main__":
    main()
