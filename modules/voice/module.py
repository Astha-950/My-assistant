"""
Voice module for HP Assistant (Stage 2.2).
Inherits from BaseModule and registers under feature "voice".
Implements an explicit 3-state machine: ACTIVE, PAUSED, SLEEP.
Supports distinct audio beeps, offline Vosk recognizers (wake & pause/resume),
dynamic tray tooltip reflection, and automatic audit logging of state transitions.
Fully thread-safe with fresh object allocation on every start().
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
from .state_machine import VoiceState, VoiceStateMachine
from .stt import SpeechToTextEngine
from .wake_word import VoskWakeDetector


def play_beep(frequency: int, duration_ms: int) -> None:
    """Safely play a tone on Windows using winsound."""
    try:
        import winsound
        winsound.Beep(frequency, duration_ms)
    except Exception:
        pass


def play_session_start_beep() -> None:
    """Distinct chime for session start (1200 Hz)."""
    play_beep(1200, 150)


def play_pause_beep() -> None:
    """Distinct tone for pause (two descending tones: 850 Hz, 600 Hz)."""
    play_beep(850, 100)
    play_beep(600, 100)


def play_resume_beep() -> None:
    """Distinct tone for resume (two ascending tones: 600 Hz, 850 Hz)."""
    play_beep(600, 100)
    play_beep(850, 100)


def play_sleep_beep() -> None:
    """Distinct chime for sleep (450 Hz, 250ms)."""
    play_beep(450, 250)


# Backward compatibility alias
play_session_end_beep = play_sleep_beep


class VoiceModule(BaseModule):
    """
    Main Voice Module managing microphone lifecycle, explicit 3-state machine
    (ACTIVE, PAUSED, SLEEP), offline wake/pause recognition, and continuous listening.
    """

    def __init__(self, controller: Optional[Any] = None, logger: Optional[logging.Logger] = None) -> None:
        self.controller = controller
        self._logger = logger or logging.getLogger("HP_Assistant.VoiceModule")

        self._state_machine = VoiceStateMachine(initial_state=VoiceState.SLEEP, logger=self._logger)
        self._wake_detector = VoskWakeDetector(logger=self._logger)
        self._stt_engine = SpeechToTextEngine(logger=self._logger)
        self._router = CommandRouter(
            controller=self.controller,
            state_machine=self._state_machine,
            logger=self._logger,
        )

        self.is_running = False
        self._lock = threading.RLock()

        # Ephemeral objects per run (always freshly allocated on start)
        self._stop_event: Optional[threading.Event] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._audio_listener: Optional[AudioListener] = None
        self._last_speech_time: float = 0.0
        self._paused_start_time: float = 0.0

        # Configuration
        config = load_config()
        voice_cfg = config.get("voice", {})
        self.session_timeout_seconds: float = float(voice_cfg.get("session_timeout_seconds", 60))
        self.pause_timeout_minutes: float = float(voice_cfg.get("pause_timeout_minutes", 10))

        self.pause_phrases: List[str] = [p.lower() for p in voice_cfg.get("pause_phrases", ["pause"])]
        self.resume_phrases: List[str] = [
            p.lower() for p in voice_cfg.get("resume_phrases", ["h p resume", "hp resume"])
        ]
        self.paused_sleep_phrases: List[str] = [
            p.lower() for p in voice_cfg.get("paused_sleep_phrases", ["h p sleep", "hp sleep"])
        ]
        self.sleep_phrases: List[str] = [
            p.lower() for p in voice_cfg.get("sleep_phrases", ["go to sleep", "sleep", "stop listening"])
        ]

    @property
    def name(self) -> str:
        return "VoiceModule"

    @property
    def state_machine(self) -> VoiceStateMachine:
        return self._state_machine

    @property
    def current_state(self) -> VoiceState:
        return self._state_machine.current_state

    @property
    def current_state_name(self) -> str:
        if not self.is_running:
            return "OFF"
        return self._state_machine.current_state.value

    @property
    def in_session(self) -> bool:
        """Backwards compatibility for session state: True when ACTIVE."""
        return self._state_machine.is_active

    @in_session.setter
    def in_session(self, val: bool) -> None:
        if val:
            self._state_machine.transition(VoiceState.ACTIVE, reason="in_session_set")
        else:
            self._state_machine.transition(VoiceState.SLEEP, reason="in_session_clear")

    def _on_state_transition(self, from_state: VoiceState, to_state: VoiceState, reason: str) -> None:
        """Trigger controller state change notification to refresh tray tooltip."""
        if to_state == VoiceState.ACTIVE:
            self._last_speech_time = time.time()
        elif to_state == VoiceState.PAUSED:
            self._paused_start_time = time.time()

        if self.controller and hasattr(self.controller, "notify_state_change"):
            try:
                self.controller.notify_state_change()
            except Exception as e:
                self._logger.debug("Error notifying controller of voice state change: %s", e)

    def start(self) -> None:
        """
        Start microphone and begin background listening loop in SLEEP state.
        Every start() creates fresh objects: stop event, mic stream, worker thread,
        fresh Vosk recognizers, and fresh state machine.
        """
        with self._lock:
            if self.is_running:
                return

            self._logger.info("Starting VoiceModule (creating fresh audio/thread/Vosk objects)...")

            # 1. Fresh stop event
            self._stop_event = threading.Event()

            # 2. Fresh state machine starting in SLEEP
            self._state_machine = VoiceStateMachine(initial_state=VoiceState.SLEEP, logger=self._logger)
            self._state_machine.add_listener(self._on_state_transition)
            self._router.state_machine = self._state_machine

            # 3. Fresh Vosk recognizer instances (both wake and paused)
            if not self._wake_detector.initialize():
                self._logger.warning("Could not initialize wake-word engine. Using fallback.")
            else:
                self._wake_detector.create_fresh_recognizer()
                self._wake_detector.create_fresh_paused_recognizer()

            # 4. Fresh microphone stream
            self._audio_listener = AudioListener(logger=self._logger)
            if not self._audio_listener.start():
                self._logger.error("Failed to open microphone stream. VoiceModule not started.")
                return

            # 5. Fresh daemon worker thread
            self.is_running = True
            self._worker_thread = threading.Thread(
                target=self._run_voice_loop,
                name="VoiceWorkerThread",
                daemon=True,
            )
            self._worker_thread.start()

            # Notify controller so tray tooltip updates to [Voice: Sleeping]
            if self.controller and hasattr(self.controller, "notify_state_change"):
                self.controller.notify_state_change()

            self._logger.info("VoiceModule started. Initial state: SLEEP. Listening for 'wake up HP'...")

    def stop(self) -> None:
        """
        Close microphone stream, signal worker thread, and join with timeout (3s).
        Fully releases all resources and supports unlimited restart cycles from ANY state.
        """
        with self._lock:
            if not self.is_running:
                return

            self._logger.info("Stopping VoiceModule from state %s...", self.current_state_name)

            # Transition to SLEEP / OFF and play sleep beep if active/paused
            if self._state_machine.is_active or self._state_machine.is_paused:
                play_sleep_beep()
                self._state_machine.reset(reason="voice_stopped")

            # Signal worker thread to terminate
            if self._stop_event:
                self._stop_event.set()

            # Fully close microphone stream
            if self._audio_listener:
                self._audio_listener.stop()

            # Join thread with strict 3-second timeout
            if self._worker_thread:
                if self._worker_thread.is_alive():
                    self._worker_thread.join(timeout=3.0)
                    if self._worker_thread.is_alive():
                        self._logger.warning("Voice worker thread did not join within 3s timeout.")
                self._worker_thread = None

            self.is_running = False

            # Notify controller to refresh tray tooltip to [Voice: OFF]
            if self.controller and hasattr(self.controller, "notify_state_change"):
                self.controller.notify_state_change()

            self._logger.info("VoiceModule stopped. Microphone stream closed and threads joined.")

    def _run_voice_loop(self) -> None:
        """
        Main worker loop driving the 3-state machine:
        - SLEEP: offline Vosk listens for 'wake up HP'.
        - PAUSED: offline Vosk listens ONLY for 'HP resume' or 'HP sleep'. No Google API.
        - ACTIVE: continuous listening via SpeechRecognition; routes commands, handles pause & sleep.
        """
        self._last_speech_time = time.time()
        self._paused_start_time = time.time()

        while self._stop_event and not self._stop_event.is_set():
            # =============================================================
            # STATE 1: SLEEP (Offline wake phrase detection)
            # =============================================================
            if self._state_machine.is_sleeping:
                if not self._audio_listener:
                    break
                chunk = self._audio_listener.read_chunk(timeout=0.05)
                if not chunk or self._stop_event.is_set():
                    continue

                if self._wake_detector.process_chunk(chunk):
                    self._logger.info("Wake phrase detected! Transitioning SLEEP -> ACTIVE.")
                    self._state_machine.transition(VoiceState.ACTIVE, reason="wake_phrase_detected")
                    play_session_start_beep()
                    self._last_speech_time = time.time()

            # =============================================================
            # STATE 2: PAUSED (Offline restricted recognizer only)
            # =============================================================
            elif self._state_machine.is_paused:
                # Check for pause timeout (default 10 minutes)
                if (time.time() - self._paused_start_time) > (self.pause_timeout_minutes * 60):
                    self._logger.info("Paused state timed out after %s minutes. Transitioning PAUSED -> SLEEP.", self.pause_timeout_minutes)
                    self._state_machine.transition(VoiceState.SLEEP, reason="pause_timeout")
                    play_sleep_beep()
                    continue

                if not self._audio_listener:
                    break
                chunk = self._audio_listener.read_chunk(timeout=0.05)
                if not chunk or self._stop_event.is_set():
                    continue

                # Process chunk ONLY through restricted offline Vosk recognizer
                action = self._wake_detector.process_paused_chunk(chunk)
                if action == "resume":
                    self._logger.info("Resume phrase detected! Transitioning PAUSED -> ACTIVE.")
                    self._state_machine.transition(VoiceState.ACTIVE, reason="user_resume")
                    play_resume_beep()
                    speak("Resumed.")
                    self._last_speech_time = time.time()
                elif action == "sleep":
                    self._logger.info("Sleep phrase detected in pause! Transitioning PAUSED -> SLEEP.")
                    self._state_machine.transition(VoiceState.SLEEP, reason="user_sleep")
                    play_sleep_beep()
                    speak("Going to sleep.")

            # =============================================================
            # STATE 3: ACTIVE (Continuous multi-command session mode)
            # =============================================================
            elif self._state_machine.is_active:
                # Check session inactivity timeout (default 60 seconds)
                if (time.time() - self._last_speech_time) > self.session_timeout_seconds:
                    self._logger.info("Session timed out after %ss of inactivity. Transitioning ACTIVE -> SLEEP.", self.session_timeout_seconds)
                    self._state_machine.transition(VoiceState.SLEEP, reason="session_timeout")
                    play_sleep_beep()
                    continue

                # Record audio chunk for speech transcription (up to 4 seconds)
                if not self._audio_listener:
                    break
                command_pcm = self._audio_listener.record_seconds(duration=4.0, stop_event=self._stop_event)
                if self._stop_event.is_set():
                    break

                if not command_pcm or len(command_pcm) < 8000:
                    continue

                # Transcribe speech via Google Web API
                text = self._stt_engine.recognize_pcm(command_pcm)
                if not text:
                    continue

                self._logger.info("Active session received speech: '%s'", text)
                self._last_speech_time = time.time()

                lower_text = text.lower().strip()

                # A. Check for "pause" command
                if any(phrase == lower_text or phrase in lower_text.split() for phrase in self.pause_phrases):
                    self._logger.info("Pause phrase recognized. Transitioning ACTIVE -> PAUSED.")
                    # Requirement: If a permission confirmation popup is open when pause is requested, deny it.
                    if permissions.is_confirmation_active():
                        permissions.voice_confirm(False)
                        self._logger.info("Auto-denied open permission confirmation popup on pause request.")

                    self._state_machine.transition(VoiceState.PAUSED, reason="user_pause")
                    play_pause_beep()
                    speak("Paused.")
                    self._paused_start_time = time.time()
                    continue

                # B. Check for "go to sleep" / "sleep" commands
                if any(phrase in lower_text for phrase in self.sleep_phrases):
                    self._logger.info("Sleep phrase recognized. Transitioning ACTIVE -> SLEEP.")
                    self._state_machine.transition(VoiceState.SLEEP, reason="user_sleep")
                    play_sleep_beep()
                    speak("Going to sleep.")
                    if "stop listening" in lower_text or "turn off voice" in lower_text:
                        if self.controller:
                            self.controller.turn_off_feature("voice")
                        break
                    continue

                # C. Guarded command execution in ACTIVE state
                self._router.handle(text, state=VoiceState.ACTIVE.value)
