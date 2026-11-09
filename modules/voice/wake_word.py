"""
Offline wake word detection using Vosk with restricted grammar.
Creates a fresh KaldiRecognizer on every start to prevent stale state issues.
"""

import json
import logging
import os
from typing import Any, Dict, Optional
import urllib.request
import zipfile

import vosk

from core.config import load_config

# Disable Vosk verbose C logging by default
vosk.SetLogLevel(-1)


def ensure_vosk_model(model_name: str, model_url: str, models_root: str = "models") -> str:
    """Ensure Vosk model exists locally in models_root, downloading if needed."""
    model_dir = os.path.join(models_root, model_name)
    if os.path.exists(model_dir):
        return model_dir

    os.makedirs(models_root, exist_ok=True)
    zip_path = os.path.join(models_root, f"{model_name}.zip")

    logger = logging.getLogger("HP_Assistant.Vosk")
    logger.info("Downloading small Vosk model from %s ...", model_url)

    urllib.request.urlretrieve(model_url, zip_path)

    logger.info("Extracting Vosk model to %s ...", models_root)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(models_root)

    if os.path.exists(zip_path):
        os.remove(zip_path)

    logger.info("Vosk model successfully prepared at %s", model_dir)
    return model_dir


class VoskWakeDetector:
    """
    Offline wake-word engine.
    Always creates a fresh KaldiRecognizer on each run to support unlimited cycles.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, logger: Optional[logging.Logger] = None) -> None:
        self._config = config or load_config()
        self._logger = logger or logging.getLogger("HP_Assistant.WakeWord")

        voice_cfg = self._config.get("voice", {})
        self.wake_word = voice_cfg.get("wake_word", "wake up HP").strip().lower()
        self.model_name = voice_cfg.get("vosk_model_name", "vosk-model-small-en-in-0.4")
        self.model_url = voice_cfg.get(
            "vosk_model_url",
            "https://alphacephei.com/vosk/models/vosk-model-small-en-in-0.4.zip",
        )
        self.sample_rate = voice_cfg.get("sample_rate", 16000)

        # Build grammar lists: handle "HP" as both "h p" and "hp"
        words = ["wake up h p", "wake up hp", "[unk]"]
        self.grammar_json = json.dumps(words)

        resume_phrases = [p.lower() for p in voice_cfg.get("resume_phrases", ["h p resume", "hp resume"])]
        paused_sleep_phrases = [p.lower() for p in voice_cfg.get("paused_sleep_phrases", ["h p sleep", "hp sleep"])]
        paused_words = list(set(resume_phrases + paused_sleep_phrases + ["[unk]"]))
        self.paused_grammar_json = json.dumps(paused_words)

        self.resume_phrases = resume_phrases
        self.paused_sleep_phrases = paused_sleep_phrases

        self._model: Optional[vosk.Model] = None
        self._recognizer: Optional[vosk.KaldiRecognizer] = None
        self._paused_recognizer: Optional[vosk.KaldiRecognizer] = None

    def initialize(self) -> bool:
        """Ensure model is loaded and create fresh recognizers."""
        try:
            if self._model is None:
                model_path = ensure_vosk_model(self.model_name, self.model_url)
                self._model = vosk.Model(model_path)

            # Always create brand-new KaldiRecognizer instances
            self.create_fresh_recognizer()
            self.create_fresh_paused_recognizer()
            return True
        except Exception as e:
            self._logger.error("Failed to initialize Vosk model: %s", e)
            return False

    def create_fresh_recognizer(self) -> None:
        """Create a fresh wake-word recognizer instance, discarding previous state."""
        if self._model is not None:
            self._recognizer = vosk.KaldiRecognizer(self._model, self.sample_rate, self.grammar_json)
            self._recognizer.SetWords(False)
            self._logger.info("Fresh Vosk KaldiRecognizer instance created.")

    def create_fresh_paused_recognizer(self) -> None:
        """Create a fresh paused-state recognizer instance (only accepts HP resume / HP sleep)."""
        if self._model is not None:
            self._paused_recognizer = vosk.KaldiRecognizer(self._model, self.sample_rate, self.paused_grammar_json)
            self._paused_recognizer.SetWords(False)
            self._logger.info("Fresh Vosk Paused KaldiRecognizer instance created.")

    def reset(self) -> None:
        """Reset or recreate wake-word recognizer."""
        if self._recognizer:
            try:
                self._recognizer.Reset()
            except Exception:
                self.create_fresh_recognizer()

    def reset_paused(self) -> None:
        """Reset or recreate paused recognizer."""
        if self._paused_recognizer:
            try:
                self._paused_recognizer.Reset()
            except Exception:
                self.create_fresh_paused_recognizer()

    def process_chunk(self, pcm_bytes: bytes) -> bool:
        """
        Process a chunk of 16kHz 16-bit mono audio.
        Returns True if the wake phrase was detected, False otherwise.
        """
        if not self._recognizer:
            return False

        try:
            if self._recognizer.AcceptWaveform(pcm_bytes):
                res = json.loads(self._recognizer.Result())
                text = res.get("text", "").lower()
                if "wake up h p" in text or "wake up hp" in text or "wake up" in text:
                    self.reset()
                    return True
            else:
                partial = json.loads(self._recognizer.PartialResult())
                ptext = partial.get("partial", "").lower()
                if "wake up h p" in ptext or "wake up hp" in ptext:
                    self.reset()
                    return True
        except Exception as e:
            self._logger.debug("Error processing audio chunk in Vosk: %s", e)

        return False

    def process_paused_chunk(self, pcm_bytes: bytes) -> Optional[str]:
        """
        Process a chunk of audio while in PAUSED state.
        Restricted grammar only detects 'HP resume' or 'HP sleep'.
        Returns 'resume', 'sleep', or None.
        """
        if not self._paused_recognizer:
            return None

        try:
            detected_text = ""
            if self._paused_recognizer.AcceptWaveform(pcm_bytes):
                res = json.loads(self._paused_recognizer.Result())
                detected_text = res.get("text", "").lower()
            else:
                partial = json.loads(self._paused_recognizer.PartialResult())
                detected_text = partial.get("partial", "").lower()

            if detected_text:
                for phrase in self.resume_phrases:
                    if phrase in detected_text or "resume" in detected_text:
                        self.reset_paused()
                        return "resume"
                for phrase in self.paused_sleep_phrases:
                    if phrase in detected_text or "sleep" in detected_text:
                        self.reset_paused()
                        return "sleep"
        except Exception as e:
            self._logger.debug("Error processing paused audio chunk in Vosk: %s", e)

        return None
