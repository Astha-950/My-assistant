"""
Speech-to-Text (STT) processor using SpeechRecognition library and Google Web API.
Captures follow-up command after wake phrase detection, plays audio cue,
and handles timeouts and offline errors gracefully without crashing.
"""

import logging
import time
from typing import Optional

import speech_recognition as sr

from core.config import load_config
from core.tts import speak


def play_wake_beep() -> None:
    """Play a short audio cue after wake phrase is detected."""
    try:
        import winsound
        winsound.Beep(1200, 150)
    except Exception:
        pass


class SpeechToTextEngine:
    """
    Handles command speech recognition using Google Web Speech API.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger("HP_Assistant.STT")
        self._recognizer = sr.Recognizer()
        config = load_config()
        voice_cfg = config.get("voice", {})
        self.language = voice_cfg.get("stt_language", "en-IN")
        self.timeout_seconds = voice_cfg.get("stt_timeout_seconds", 6)

    def recognize_pcm(self, pcm_bytes: bytes, sample_rate: int = 16000) -> Optional[str]:
        """
        Convert raw 16kHz 16-bit mono PCM bytes to text using Google Speech API.
        """
        if not pcm_bytes or len(pcm_bytes) < sample_rate * 0.5:
            self._logger.info("Audio buffer too short for command recognition.")
            return None

        audio_data = sr.AudioData(pcm_bytes, sample_rate, 2)

        try:
            text = self._recognizer.recognize_google(audio_data, language=self.language)
            self._logger.info("Recognized command: '%s'", text)
            return text.strip().lower()
        except sr.UnknownValueError:
            self._logger.info("Speech recognition could not understand audio.")
            speak("Sorry, I could not understand that.")
            return None
        except sr.RequestError as e:
            self._logger.warning("Google Speech Recognition service unreachable: %s", e)
            speak("I am having trouble connecting to the speech service.")
            return None
        except Exception as e:
            self._logger.error("Unexpected error in speech recognition: %s", e)
            return None

