# HP Assistant - Stage 2.1

HP Assistant is a modular, privacy-first desktop assistant designed for Windows.

This repository represents **Stage 2.1: Voice Pipeline & Continuous Session Mode** (built on top of Stage 1 and Stage 1.5). It delivers a robust hands-free voice loop with continuous multi-command session mode, instant restart recovery, and graceful process termination.

> **Stage 2.1 Scope:** Implements the voice pipeline (`wake phrase -> continuous session listen -> STT -> TTS`), restart resilience across unlimited ON/OFF cycles, Ctrl+C shutdown, and session control (`"go to sleep"` / timeout). Camera, gestures, and real laptop-control actions will be introduced in subsequent stages.

---

## Architecture & Project Structure

```text
My_assistant/
│
├── main.py                   # Application entry point and module registration
├── config.json               # Configuration (hotkeys, voice, permissions)
├── requirements.txt          # Python dependencies
├── README.md                 # Setup, usage, and developer documentation
├── pytest.ini                # Pytest configuration
├── .gitignore                # Git exclusions (venv, logs, models, audio, cache)
│
├── core/
│   ├── __init__.py           # Package exports
│   ├── config.py             # Configuration loader and logging setup
│   ├── controller.py         # Master controller and per-feature switches
│   ├── permissions.py        # Central security permission gateway & audit log
│   ├── tray.py               # System tray icon, menu, checkmarks, & mic active indicator
│   └── tts.py                # Global speak() engine (edge-tts + pygame, mic auto-mute)
│
├── modules/
│   ├── __init__.py
│   └── voice/
│       ├── __init__.py       # Package exports (VoiceModule, CommandRouter)
│       ├── module.py         # VoiceModule lifecycle inheriting BaseModule
│       ├── audio_listener.py # Real-time microphone capture via sounddevice (16kHz mono)
│       ├── wake_word.py      # Offline wake-word detection (Vosk with restricted grammar)
│       ├── stt.py            # Speech-to-Text engine via Google Speech API (en-IN)
│       └── router.py         # Command routing and permission confirmation hook
│
└── tests/
    ├── __init__.py
    ├── test_config.py        # Configuration unit tests
    ├── test_controller.py    # Master controller state and idempotency tests
    ├── test_feature_toggles.py # Feature toggle hierarchy (Voice/Gestures) tests
    ├── test_permissions.py   # Security tiers, popup, timeout, and audit tests
    └── test_voice_module.py  # Voice pipeline, routing, and mock lifecycle tests
```

---

## Voice Pipeline Features (Stage 2)

### 1. Voice Module Integration (`modules/voice/`)
- Registered under feature **`"voice"`** with [`core/controller.py`](file:///c:/Users/hp/OneDrive/Documents/My_assistant/core/controller.py).
- **Strict Resource Control**:
  - `start()` opens the microphone stream and launches background worker threads.
  - `stop()` forcefully closes the audio stream, stops threads, and releases audio devices.
  - When Master or Voice toggle is **OFF**, the microphone stream is completely closed.

### 2. Offline Wake Phrase Detection (`modules/voice/wake_word.py`)
- **Phrase**: `"wake up HP"` (configurable in `config.json`).
- **Engine**: **Vosk** offline speech model (`vosk-model-small-en-in-0.4`).
  - Auto-downloaded on first run into `models/` (git-ignored).
  - Uses **restricted grammar** (`["wake up h p", "wake up hp", "[unk]"]`) for near-zero latency, minimal CPU overhead, and high accuracy.
- **Privacy Guarantee**: All audio is processed purely in local memory; zero audio or data is transmitted over the network until the wake phrase is detected.

### 3. Speech-to-Text (`modules/voice/stt.py`)
- After the wake phrase is detected:
  - Plays a short audio beep cue (1200 Hz).
  - Captures the follow-up voice command (timeout: ~6 seconds).
  - Transcribes using the **SpeechRecognition** library with Google Web Speech API in `en-IN`.
- **Fault-Tolerant**: Network errors, timeouts, or unintelligible speech are caught gracefully with spoken feedback without crashing.

### 4. Text-to-Speech & Auto-Mute (`core/tts.py`)
- Provides `core.speak(text)` available globally across all assistant modules.
- **High-Quality Voice**: Uses `edge-tts` with voice `en-IN-NeerjaNeural` played through `pygame.mixer`. Temporary audio files are deleted immediately after playback.
- **Microphone Auto-Mute**: Automatically mutes the microphone stream while speaking to prevent the assistant from hearing and re-triggering itself.
- **Offline Fallback**: Automatically falls back to `pyttsx3` if offline.

### 5. Command Router (`modules/voice/router.py`)
Maps recognized phrases to handlers:
1. **Stage 1.5 Permission Hook**:
   - If a permission confirmation popup is currently awaiting response:
     - Saying `"yes"` / `"confirm"` / `"allow"` calls `permissions.voice_confirm(True)`.
     - Saying `"no"` / `"cancel"` / `"deny"` calls `permissions.voice_confirm(False)`.
2. **`"what time is it"`**: Announces the current system time.
3. **`"hello"`**: Greets the user.
4. **`"stop listening"`**: Deactivates the Voice feature through the controller (`controller.turn_off_feature("voice")`).

### 6. Privacy & Tray Indicator
- **Zero Audio Storage**: Audio buffers exist strictly in RAM and are discarded immediately.
- **Audit Logging**: Events (wake detected, command text, execution result) are logged to `logs/audit.log`.
- **Tray Tooltip**: The tray icon tooltip dynamically displays `[Mic Active]` whenever the voice feature is actively capturing audio.

---

## Configuration (`config.json`)

```json
{
  "app_name": "HP Assistant",
  "version": "2.0.0",
  "hotkey_enabled": false,
  "hotkey": "ctrl+alt+h",
  "beep_on_toggle": true,
  "toast_on_toggle": true,
  "log_file": "logs/assistant.log",
  "log_level": "INFO",
  "voice": {
    "wake_word": "wake up HP",
    "vosk_model_name": "vosk-model-small-en-in-0.4",
    "vosk_model_url": "https://alphacephei.com/vosk/models/vosk-model-small-en-in-0.4.zip",
    "stt_language": "en-IN",
    "stt_timeout_seconds": 6,
    "tts_voice": "en-IN-NeerjaNeural",
    "sample_rate": 16000
  },
  "permissions": { ... }
}
```

---

## How to Test by Speaking (Session Mode & Toggles)

1. **Launch the Assistant**:
   ```powershell
   python main.py
   ```
2. **Turn on Master and Voice**:
   - Right-click the red tray icon &rarr; click **Turn ON** (icon turns green).
   - Right-click the tray icon &rarr; click **Voice: OFF** (turns into `Voice: ON` with a checkmark, tooltip shows `[Mic Active]`).
3. **Session Mode (Multiple Commands after 1 Wake)**:
   - Say the wake phrase once:
     > *"Wake up HP"*
   - You will hear a high chime (1200 Hz). The assistant is now in an **active session**!
   - Issue multiple commands continuously without repeating the wake phrase:
     - Command 1: *"What time is it"* &rarr; Assistant answers time.
     - Command 2: *"Hello"* &rarr; Assistant responds: *"Hello! How can I help you?"*
   - End the session by saying:
     > *"Go to sleep"* (or *"sleep"*)
   - You will hear a lower chime (600 Hz). The assistant exits the session and returns to waiting for the wake phrase.
   - Alternatively, staying silent for 60 seconds (or `session_timeout_seconds`) will automatically time out and close the session.
4. **Test Unlimited Start/Stop Cycling**:
   - In the tray, click **Voice: ON** to turn it OFF, then ON again.
   - Repeat this 5+ times. The wake phrase will detect normally every time because fresh stream and Vosk recognizer objects are instantiated on every cycle.
5. **Test Clean Ctrl+C**:
   - In the terminal running `main.py`, press `Ctrl+C`.
   - The application intercepts `SIGINT`, unhooks resources, turns off the controller, and terminates cleanly within 3 seconds.

---

## Running Tests

Execute the full pytest suite (45 tests):
```powershell
pytest -v
```

To run the voice module tests specifically:
```powershell
pytest tests/test_voice_module.py -v
```
