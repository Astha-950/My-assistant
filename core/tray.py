"""
System tray integration for HP Assistant using pystray and Pillow.
Provides dynamic green/red status icons, right-click menu controls with
per-feature toggles (Voice, Gestures), checkmarks, mic active tooltip indicators,
notifications, and audio feedback.
"""

import logging
import os
import threading
from typing import Any, Callable, Dict, Optional
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

from .controller import AssistantController


def create_tray_icon_image(is_on: bool, size: int = 64) -> Image.Image:
    """
    Generate dynamic tray icon with Pillow.
    Green circle when ON, Red circle when OFF.
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Theme colors
    # ON: Emerald Green (#22C55E)
    # OFF: Rose Red (#EF4444)
    fill_color = (34, 197, 94, 255) if is_on else (239, 68, 68, 255)
    border_color = (255, 255, 255, 230)

    # Main outer circle
    draw.ellipse([4, 4, size - 5, size - 5], fill=fill_color, outline=border_color, width=3)

    # Inner indicator mark (power circle symbol)
    center = size // 2
    inner_radius = size // 4
    draw.ellipse(
        [center - inner_radius, center - inner_radius, center + inner_radius, center + inner_radius],
        outline=(255, 255, 255, 240),
        width=2,
    )

    return image


def _play_beep_async(is_on: bool) -> None:
    """Play a short beep in background thread to avoid blocking GUI."""
    try:
        import winsound
        # High pitch for ON (1000 Hz), lower pitch for OFF (600 Hz)
        frequency = 1000 if is_on else 600
        duration_ms = 150
        winsound.Beep(frequency, duration_ms)
    except Exception:
        pass


class TrayApp:
    """
    Manages the system tray icon, state sync, notifications, and menu actions.
    Supports master switch, per-feature switches (Voice, Gestures) with checkmarks,
    and mic active tooltip indicator.
    """

    def __init__(
        self,
        controller: AssistantController,
        config: Dict[str, Any],
        cleanup_callback: Optional[Callable[[], None]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.controller = controller
        self.config = config
        self._cleanup_callback = cleanup_callback
        self._logger = logger or logging.getLogger("HP_Assistant.Tray")

        # Cache pre-rendered icons
        self._icon_on = create_tray_icon_image(is_on=True)
        self._icon_off = create_tray_icon_image(is_on=False)

        # Dynamic menu titles and state callbacks
        def voice_title(item: Any) -> str:
            return f"Voice: {'ON' if self.controller.is_feature_on('voice') else 'OFF'}"

        def is_voice_checked(item: Any) -> bool:
            return self.controller.is_feature_on("voice")

        def gestures_title(item: Any) -> str:
            return f"Gestures: {'ON' if self.controller.is_feature_on('gestures') else 'OFF'}"

        def is_gestures_checked(item: Any) -> bool:
            return self.controller.is_feature_on("gestures")

        # Setup menu with Master controls, Feature toggles with checkmarks, and Quit
        menu = pystray.Menu(
            item("Turn ON", self._on_turn_on),
            item("Turn OFF", self._on_turn_off),
            pystray.Menu.SEPARATOR,
            item(voice_title, self._on_toggle_voice, checked=is_voice_checked),
            item(gestures_title, self._on_toggle_gestures, checked=is_gestures_checked),
            pystray.Menu.SEPARATOR,
            item("Quit completely", self._on_quit),
        )

        initial_icon = self._icon_on if self.controller.is_on else self._icon_off

        self._icon = pystray.Icon(
            name="HP_Assistant",
            icon=initial_icon,
            title=self._get_title(),
            menu=menu,
        )

        # Register state listener with controller
        self.controller.add_listener(self._on_state_changed)

    def _get_title(self) -> str:
        """Dynamic tooltip title indicating master state and active mic status."""
        mic_indicator = " [Mic Active]" if self.controller.is_feature_on("voice") else ""
        return f"HP Assistant - {self.controller.state_name}{mic_indicator}"

    def _on_state_changed(self, is_on: bool) -> None:
        """Handle state change event from controller."""
        if self._icon:
            self._icon.icon = self._icon_on if is_on else self._icon_off
            self._icon.title = self._get_title()
            if hasattr(self._icon, "update_menu"):
                try:
                    self._icon.update_menu()
                except Exception:
                    pass

        # Beep feedback
        if self.config.get("beep_on_toggle", True):
            threading.Thread(target=_play_beep_async, args=(is_on,), daemon=True).start()

        # Toast / balloon feedback
        if self.config.get("toast_on_toggle", True):
            threading.Thread(target=self._show_toast, args=(is_on,), daemon=True).start()

    def _show_toast(self, is_on: bool) -> None:
        """Display Windows tray notification."""
        if self._icon and hasattr(self._icon, "notify"):
            try:
                state_text = "ON (Active)" if is_on else "OFF (Inactive)"
                self._icon.notify(
                    message=f"HP Assistant master state is now {state_text}.",
                    title="HP Assistant",
                )
            except Exception as e:
                self._logger.debug("Failed to show toast notification: %s", e)

    def _on_turn_on(self, icon: Optional[pystray.Icon] = None, item: Optional[Any] = None) -> None:
        """Menu handler: Turn ON Master switch."""
        self._logger.info("Tray action: Master Turn ON requested")
        self.controller.turn_on()

    def _on_turn_off(self, icon: Optional[pystray.Icon] = None, item: Optional[Any] = None) -> None:
        """Menu handler: Turn OFF Master switch (forces all features OFF)."""
        self._logger.info("Tray action: Master Turn OFF requested")
        self.controller.turn_off()

    def _on_toggle_voice(self, icon: Optional[pystray.Icon] = None, item: Optional[Any] = None) -> None:
        """Menu handler: Toggle Voice feature."""
        if not self.controller.is_on:
            self._logger.warning("Cannot toggle voice: Master is OFF")
            if self._icon and hasattr(self._icon, "notify"):
                try:
                    self._icon.notify("Master switch is OFF. Turn Master ON first.", "HP Assistant")
                except Exception:
                    pass
            return

        new_state = self.controller.toggle_feature("voice")
        self._logger.info("Tray action: Voice feature toggled to %s", "ON" if new_state else "OFF")
        if self._icon:
            self._icon.title = self._get_title()
            if hasattr(self._icon, "update_menu"):
                try:
                    self._icon.update_menu()
                except Exception:
                    pass

    def _on_toggle_gestures(self, icon: Optional[pystray.Icon] = None, item: Optional[Any] = None) -> None:
        """Menu handler: Toggle Gestures feature."""
        if not self.controller.is_on:
            self._logger.warning("Cannot toggle gestures: Master is OFF")
            if self._icon and hasattr(self._icon, "notify"):
                try:
                    self._icon.notify("Master switch is OFF. Turn Master ON first.", "HP Assistant")
                except Exception:
                    pass
            return

        new_state = self.controller.toggle_feature("gestures")
        self._logger.info("Tray action: Gestures feature toggled to %s", "ON" if new_state else "OFF")
        if self._icon:
            self._icon.title = self._get_title()
            if hasattr(self._icon, "update_menu"):
                try:
                    self._icon.update_menu()
                except Exception:
                    pass

    def _on_quit(self, icon: Optional[pystray.Icon] = None, item: Optional[Any] = None) -> None:
        """
        Menu handler: Quit completely.
        Calls turn_off() (which forces features off), stops tray icon, invokes cleanup, and fully exits.
        """
        self._logger.info("Tray action: Quit completely requested. Shutting down...")
        try:
            self.controller.turn_off()
        except Exception as e:
            self._logger.error("Error during controller turn_off on exit: %s", e)

        if self._cleanup_callback:
            try:
                self._cleanup_callback()
            except Exception as e:
                self._logger.error("Error in cleanup callback: %s", e)

        if self._icon:
            try:
                self._icon.stop()
            except Exception as e:
                self._logger.error("Error stopping tray icon: %s", e)

        self._logger.info("HP Assistant fully exited.")
        os._exit(0)

    def run(self) -> None:
        """Run system tray icon event loop (blocking)."""
        self._logger.info("Starting system tray loop...")
        self._icon.run()

    def stop(self) -> None:
        """Stop system tray icon."""
        if self._icon:
            self._icon.stop()
