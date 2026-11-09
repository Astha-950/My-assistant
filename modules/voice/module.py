"""
Voice module for HP Assistant (Stage 2).
Inherits from BaseModule and registers under feature "voice".
Manages offline wake-phrase detection (Vosk), speech-to-text (Google Web API),
command routing, and text-to-speech feedback.
"""

import logging
import threading
import time
from typing import Any, Optional

from core.controller import BaseModule
from core.permissions import permissions
from .audio_listener import AudioListener
from .router import CommandRouter
from .stt import SpeechToTextEngine, play_wake_beep
from .wake_word import VoskWakeDetector


class VoiceModule(BaseModule):
    """
    Main Voice Module managing microphone lifecycle, wake-word detection,
    and speech command execution.
    """

    def __init__(self, controller: Optional[Any] = None, logger: Optional[logging.Logger] = None) -> None:
        self.controller = controller
        self._logger = logger or logging.getLogger("HP_Assistant.VoiceModule")

        self._audio_listener = AudioListener(logger=self._logger)
        self._wake_detector = VoskWakeDetector(logger=self._logger)
        self._stt_engine = SpeechToTextEngine(logger=self._logger)
        self._router = CommandRouter(controller=self.controller, logger=self._logger)

        self.is_running = False
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    @property
    def name(self) -> str:
        return "VoiceModule"

    def start(self) -> None:
        """Start microphone and begin background listening loop."""
        if self.is_running:
            return

        self._stop_event.clear()

        # 1. Initialize Vosk model
        if not self._wake_detector.initialize():
            self._logger.warning("Could not initialize wake-word engine. Voice listening will start with fallback.")

        # 2. Open microphone stream
        if not self._audio_listener.start():
            self._logger.error("Failed to start audio stream. Voice module not started.")
            return

        # 3. Launch background listening thread
        self.is_running = True
        self._worker_thread = threading.Thread(target=self._listen_loop, name="VoiceListenThread", daemon=True)
        self._worker_thread.start()
        self._logger.info("VoiceModule started. Listening for wake phrase 'wake up HP'...")

    def stop(self) -> None:
        """Close microphone stream, stop worker threads, and release resources."""
        if not self.is_running:
            return

        self._logger.info("Stopping VoiceModule...")
        self._stop_event.set()

        # 1. Stop audio listener stream
        self._audio_listener.stop()

        # 2. Join background worker thread
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None

        self.is_running = False
        self._logger.info("VoiceModule stopped. Microphone stream fully closed.")

    def _listen_loop(self) -> None:
        """Background loop reading audio chunks and checking for wake phrase."""
        while not self._stop_event.is_set():
            chunk = self._audio_listener.read_chunk(timeout=0.2)
            if not chunk or self._stop_event.is_set():
                continue

            # Check for wake word
            if self._wake_detector.process_chunk(chunk):
                self._logger.info("Wake phrase detected!")
                permissions._write_audit_log(
                    "voice_wake_word",
                    "safe",
                    "allowed",
                    "Wake phrase 'wake up HP' detected",
                )

                # Play audio beep cue
                play_wake_beep()

                # Listen for command (up to 5.5 seconds)
                command_pcm = self._audio_listener.record_seconds(duration=5.5)
                if self._stop_event.is_set():
                    break

                # Transcribe command speech
                text = self._stt_engine.recognize_pcm(command_pcm)
                if text:
                    permissions._write_audit_log(
                        "voice_command_recognized",
                        "safe",
                        "allowed",
                        f"Speech: '{text}'",
                    )
                    self._router.handle(text)
                else:
                    self._logger.info("No command speech recognized after wake phrase.")

                # Reset wake detector state
                self._wake_detector.reset()
