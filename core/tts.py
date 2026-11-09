"""
Text-to-Speech (TTS) engine for HP Assistant.
Uses edge-tts (voice: en-IN-NeerjaNeural) with pygame playback.
Mutes microphone while speaking so assistant does not hear itself.
Provides offline fallback to pyttsx3.
Safe loop and mixer management to support unlimited cycles without errors.
"""

import asyncio
import logging
import os
import tempfile
import threading
import time
from typing import Optional

from .config import load_config

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

_logger = logging.getLogger("HP_Assistant.TTS")
_speaking_lock = threading.Lock()
_is_speaking_flag = False


def is_speaking() -> bool:
    """Returns True if the assistant is currently speaking via TTS."""
    global _is_speaking_flag
    return _is_speaking_flag


def set_speaking(value: bool) -> None:
    """Explicitly set speaking state."""
    global _is_speaking_flag
    _is_speaking_flag = value


async def _synthesize_edge_tts(text: str, voice: str, output_path: str) -> None:
    """Synthesize speech using Microsoft Edge TTS."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def _play_audio_file(file_path: str) -> None:
    """Play audio file using pygame.mixer and block until finished."""
    import pygame

    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.04)
        pygame.mixer.music.unload()
    except Exception as e:
        _logger.warning("Pygame playback issue: %s", e)


def _fallback_pyttsx3(text: str) -> None:
    """Offline fallback using pyttsx3."""
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        _logger.warning("pyttsx3 fallback failed: %s", e)


def speak(text: str, voice: Optional[str] = None) -> None:
    """
    Speak given text using edge-tts with pygame playback.
    Creates a fresh asyncio loop per call to avoid closed loop issues.
    Mutes microphone while speaking to prevent self-triggering.
    Falls back to pyttsx3 if offline or if edge-tts fails.
    """
    global _is_speaking_flag

    if not text or not text.strip():
        return

    text = text.strip()
    config = load_config()
    voice_name = voice or config.get("voice", {}).get("tts_voice", "en-IN-NeerjaNeural")

    with _speaking_lock:
        _is_speaking_flag = True
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                temp_path = f.name

            # Create an isolated event loop for this synthesis call
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_synthesize_edge_tts(text, voice_name, temp_path))
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
                asyncio.set_event_loop(None)

            _play_audio_file(temp_path)
        except Exception as edge_err:
            _logger.warning("edge-tts playback failed (%s). Attempting pyttsx3 fallback...", edge_err)
            _fallback_pyttsx3(text)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            _is_speaking_flag = False
