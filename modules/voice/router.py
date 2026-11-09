"""
Voice command router for HP Assistant.
Maps recognized speech phrases to handlers, handles Stage 1.5 confirmation hook,
and enforces security permissions.
"""

from datetime import datetime
import logging
from typing import Any, Optional

from core.permissions import permissions
from core.tts import speak


class CommandRouter:
    """
    Parses and routes recognized voice commands.
    """

    def __init__(self, controller: Optional[Any] = None, logger: Optional[logging.Logger] = None) -> None:
        self.controller = controller
        self._logger = logger or logging.getLogger("HP_Assistant.VoiceRouter")

    def handle(self, phrase: str) -> bool:
        """
        Process recognized speech string.
        Returns True if a command was handled, False otherwise.
        """
        if not phrase or not phrase.strip():
            return False

        text = phrase.strip().lower()
        self._logger.info("Processing voice command: '%s'", text)

        # 1. Check for Active Permission Confirmation Hook
        if permissions.is_confirmation_active():
            if any(w in text for w in ("yes", "confirm", "allow", "proceed")):
                self._logger.info("Voice confirmed active permission request.")
                permissions.voice_confirm(True)
                speak("Confirmed.")
                permissions._write_audit_log("voice_confirm", "safe", "allowed", f"Phrase: '{text}'")
                return True
            elif any(w in text for w in ("no", "cancel", "deny", "stop")):
                self._logger.info("Voice denied active permission request.")
                permissions.voice_confirm(False)
                speak("Denied.")
                permissions._write_audit_log("voice_confirm", "safe", "denied", f"Phrase: '{text}'")
                return True

        # 2. Test Command: "what time is it"
        if "what time is it" in text or "what is the time" in text or "tell me the time" in text:
            now_str = datetime.now().strftime("%I:%M %p")
            response = f"The time is {now_str}."
            permissions._write_audit_log("time_query", "safe", "allowed", response)
            speak(response)
            return True

        # 3. Test Command: "hello"
        if "hello" in text or text == "hi" or "hey" in text:
            response = "Hello! How can I help you?"
            permissions._write_audit_log("greeting", "safe", "allowed", response)
            speak(response)
            return True

        # 4. Test Command: "stop listening" (turns Voice feature OFF through controller)
        if "stop listening" in text or "turn off voice" in text or "deactivate voice" in text:
            permissions._write_audit_log("stop_listening", "safe", "allowed", "Voice feature turned off")
            speak("Stopping voice recognition.")
            if self.controller:
                self.controller.turn_off_feature("voice")
            return True

        # 5. Fallback for unhandled command
        self._logger.info("Unrecognized command: '%s'", text)
        speak("I heard: " + text + ". No command matched.")
        permissions._write_audit_log("unknown_voice_command", "confirm", "denied", f"Unrecognized phrase: {text}")
        return False
