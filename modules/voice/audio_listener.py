"""
Microphone audio stream capture using sounddevice.
Captures 16kHz 16-bit mono PCM in real-time.
Mutes incoming audio while TTS is actively speaking.
Supports rapid shutdown with short timeouts and fresh stream creation per start.
"""

import logging
import queue
import threading
import time
from typing import Any, Optional

import sounddevice as sd

from core.tts import is_speaking


class AudioListener:
    """
    Manages the microphone audio input stream and buffer queue.
    Creates a fresh stream and queue on every start.
    """

    def __init__(self, sample_rate: int = 16000, block_size: int = 4000, logger: Optional[logging.Logger] = None) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._logger = logger or logging.getLogger("HP_Assistant.AudioListener")

        self._queue: queue.Queue = queue.Queue(maxsize=100)
        self._stream: Optional[sd.RawInputStream] = None
        self._is_active = False
        self._lock = threading.Lock()

    @property
    def is_active(self) -> bool:
        """Returns True if the microphone stream is open and recording."""
        with self._lock:
            return self._is_active

    def _audio_callback(self, indata: bytes, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
        """Callback from sounddevice stream."""
        if status:
            self._logger.debug("Audio stream status: %s", status)

        # Mute microphone input while assistant is speaking through TTS
        if is_speaking():
            return

        try:
            self._queue.put_nowait(bytes(indata))
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(bytes(indata))
            except queue.Empty:
                pass

    def start(self) -> bool:
        """Open a fresh microphone stream and begin capturing."""
        with self._lock:
            if self._is_active:
                return True

            try:
                # Fresh buffer queue for each start
                self._queue = queue.Queue(maxsize=100)

                self._stream = sd.RawInputStream(
                    samplerate=self.sample_rate,
                    blocksize=self.block_size,
                    channels=1,
                    dtype="int16",
                    callback=self._audio_callback,
                )
                self._stream.start()
                self._is_active = True
                self._logger.info("Fresh microphone stream opened (16kHz 16-bit mono).")
                return True
            except Exception as e:
                self._logger.error("Failed to open microphone stream: %s", e)
                self._is_active = False
                self._stream = None
                return False

    def stop(self) -> None:
        """Fully close microphone stream and release audio devices."""
        with self._lock:
            if not self._is_active:
                return

            self._is_active = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as e:
                    self._logger.debug("Error closing audio stream: %s", e)
                finally:
                    self._stream = None

            # Empty queue
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

            self._logger.info("Microphone stream closed and resources released.")

    def read_chunk(self, timeout: float = 0.05) -> Optional[bytes]:
        """
        Read a single audio chunk from the buffer with a short timeout.
        Short timeout allows worker loops to check stop events and exit quickly.
        """
        with self._lock:
            if not self._is_active:
                return None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def record_seconds(self, duration: float, stop_event: Optional[threading.Event] = None) -> bytes:
        """
        Collect audio buffer for up to duration seconds, or until stop_event is signaled.
        """
        chunks = []
        end_time = time.time() + duration
        while time.time() < end_time:
            if stop_event and stop_event.is_set():
                break
            chunk = self.read_chunk(timeout=0.05)
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)
