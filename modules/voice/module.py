"""
Voice module for HP Assistant (Stage 2.1).
Inherits from BaseModule and registers under feature "voice".
Manages offline wake-phrase detection (Vosk), continuous session mode,
speech-to-text, command routing, and text-to-speech feedback.
Fully thread-safe and supports unlimited restart cycles without leaking resources.
"""

import logging
import threading
import time
from typing import Any, List, Optional

from core.config import load_config
from core.controller import BaseModule
from core.permissions import permissions
from core.tts import speak
from .audio_listener import AudioListener
from .router import CommandRouter
from .stt import SpeechToTextEngine
from .wake_word import VoskWakeDetector


def play_session_start_beep() -> None:
    """High chime indicating session started."""
    try:
        import winsound
        winsound.Beep(1200, 150)
    except Exception:
        pass


def play_session_end_beep() -> None:
    """Lower chime indicating session ended (going to sleep)."""
    try:
        import winsound
        winsound.Beep(600, 250)
    except Exception:
        pass


class VoiceModule(BaseModule):
    """
    Main Voice Module managing microphone lifecycle, wake-phrase detection,
    and continuous session mode.
    Every start() creates fresh objects (threads, streams, stop events, recognizers).
    """

    def __init__(self, controller: Optional[Any] = None, logger: Optional[logging.Logger] = None) -> None:
        self.controller = controller
        self._logger = logger or logging.getLogger("HP_Assistant.VoiceModule")

        self._wake_detector = VoskWakeDetector(logger=self._logger)
        self._stt_engine = SpeechToTextEngine(logger=self._logger)
        self._router = CommandRouter(controller=self.controller, logger=self._logger)

        self.is_running = False
        self.in_session = False
        self._lock = threading.RLock()

        # Ephemeral objects per run (always freshly allocated on start)
        self._stop_event: Optional[threading.Event] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._audio_listener: Optional[AudioListener] = None

        # Configuration
        config = load_config()
        voice_cfg = config.get("voice", {})
        self.session_timeout_seconds: float = float(voice_cfg.get("session_timeout_seconds", 60))
        self.sleep_phrases: List[str] = [
            p.lower() for p in voice_cfg.get("sleep_phrases", ["go to sleep", "sleep", "stop listening"])
        ]

    @property
    def name(self) -> str:
        return "VoiceModule"

    def start(self) -> None:
        """
        Start microphone and begin background listening loop.
        Every start() creates a fresh stop event, fresh mic stream, fresh thread,
        and fresh Vosk recognizer.
        """
        with self._lock:
            if self.is_running:
                return

            self._logger.info("Starting VoiceModule (creating fresh audio/thread/Vosk objects)...")

            # 1. Fresh stop event
            self._stop_event = threading.Event()

            # 2. Fresh Vosk recognizer instance
            if not self._wake_detector.initialize():
                self._logger.warning("Could not initialize wake-word engine. Using fallback.")
            else:
                self._wake_detector.create_fresh_recognizer()

            # 3. Fresh microphone stream
            self._audio_listener = AudioListener(logger=self._logger)
            if not self._audio_listener.start():
                self._logger.error("Failed to open microphone stream. VoiceModule not started.")
                return

            # 4. Reset session state
            self.in_session = False

            # 5. Fresh daemon worker thread
            self.is_running = True
            self._worker_thread = threading.Thread(
                target=self._run_voice_loop,
                name="VoiceWorkerThread",
                daemon=True,
            )
            self._worker_thread.start()
            self._logger.info("VoiceModule started. Listening for wake phrase 'wake up HP'...")

    def stop(self) -> None:
        """
        Close microphone stream, signal worker thread, and join with timeout (3s).
        Fully releases all resources and supports unlimited restart cycles.
        """
        with self._lock:
            if not self.is_running:
                return

            self._logger.info("Stopping VoiceModule...")

            # End active session if open
            if self.in_session:
                play_session_end_beep()
                self.in_session = False

            # Signal worker thread to terminate
            if self._stop_event:
                self._stop_event.set()

            # Fully close microphone stream
            if self._audio_listener:
                self._audio_listener.stop()

            # Join thread with strict 3-second timeout
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=3.0)
                if self._worker_thread.is_alive():
                    self._logger.warning("Voice worker thread did not join within 3s timeout.")
                self._worker_thread = None

            self.is_running = False
            self._logger.info("VoiceModule stopped. Microphone stream closed and threads joined.")

    def _run_voice_loop(self) -> None:
        """
        Main worker loop:
        - When not in session: listens for wake phrase using Vosk.
        - When in session: continuously listens for commands without needing wake phrase
          until 'go to sleep' or session_timeout seconds of inactivity.
        """
        last_speech_time = time.time()

        while self._stop_event and not self._stop_event.is_set():
            # -------------------------------------------------------------
            # STATE A: Waiting for Wake Phrase
            # -------------------------------------------------------------
            if not self.in_session:
                if not self._audio_listener:
                    break
                chunk = self._audio_listener.read_chunk(timeout=0.05)
                if not chunk or self._stop_event.is_set():
                    continue

                if self._wake_detector.process_chunk(chunk):
                    self._logger.info("Wake phrase 'wake up HP' detected! Entering continuous session.")
                    permissions._write_audit_log(
                        "session_start",
                        "safe",
                        "allowed",
                        "Wake phrase detected. Entered continuous session mode.",
                    )
                    # Enter active session
                    self.in_session = True
                    play_session_start_beep()
                    last_speech_time = time.time()

            # -------------------------------------------------------------
            # STATE B: Continuous Active Session Mode
            # -------------------------------------------------------------
            else:
                # 1. Check for session timeout
                if time.time() - last_speech_time > self.session_timeout_seconds:
                    self._logger.info("Session timed out after %ss of inactivity.", self.session_timeout_seconds)
                    permissions._write_audit_log(
                        "session_timeout",
                        "safe",
                        "allowed",
                        f"Session ended after {self.session_timeout_seconds}s of inactivity.",
                    )
                    self.in_session = False
                    play_session_end_beep()
                    continue

                # 2. Record command audio chunk (up to 4 seconds)
                if not self._audio_listener:
                    break
                command_pcm = self._audio_listener.record_seconds(duration=4.0, stop_event=self._stop_event)
                if self._stop_event.is_set():
                    break

                if not command_pcm or len(command_pcm) < 8000:
                    continue

                # 3. Transcribe speech
                text = self._stt_engine.recognize_pcm(command_pcm)
                if not text:
                    continue

                self._logger.info("Session received speech: '%s'", text)
                last_speech_time = time.time()  # Keep session alive

                # 4. Check for 'go to sleep' / 'sleep' phrases to end session
                if any(phrase in text for phrase in ("go to sleep", "sleep")):
                    self._logger.info("Sleep phrase recognized. Exiting session mode.")
                    permissions._write_audit_log("session_sleep", "safe", "allowed", f"Phrase: '{text}'")
                    speak("Going to sleep.")
                    self.in_session = False
                    play_session_end_beep()
                    continue

                # 5. Check for 'stop listening' (deactivates feature completely)
                if "stop listening" in text or "turn off voice" in text:
                    self.in_session = False
                    self._router.handle(text)
                    break

                # 6. Route command (confirmation hook, what time is it, hello, etc.)
                self._router.handle(text)
                # Assistant remains in session mode for subsequent commands!
