# HP Assistant - Stage 2.2

HP Assistant is a modular, privacy-first desktop assistant designed for Windows.

This repository represents **Stage 2.2: Three-State Voice Machine (ACTIVE, PAUSED, SLEEP)** (built on top of Stage 1, Stage 1.5, and Stage 2.1). It provides a full voice state machine with distinct audio beeps, restricted offline grammar in paused mode, dynamic tray status tooltips, and transition audit logging.

> **Stage 2.2 Scope:** Implements the explicit 3-state voice machine (`ACTIVE`, `PAUSED`, `SLEEP`), distinct audio cues, tray tooltip status (`Voice: Active / Paused / Sleeping`), and offline pause/resume recognition. Camera, gestures, and real laptop-control actions will be introduced in subsequent stages.

---

## Three Voice States (Stage 2.2)

```text
               "wake up HP"
  +-------------------------------------+
  |                                     |
  v                                     |
+-------------------+  "pause"   +-------------------+
|      ACTIVE       | ---------> |      PAUSED       |
| (Continuous STT)  | <--------- | (Offline Vosk     |
+-------------------+ "HP resume"|  Restricted Only) |
  |           |                  +-------------------+
  |           |                     |             |
  | "sleep"   | 60s silence         | "HP sleep"  | 10m timeout
  v           v                     v             v
+----------------------------------------------------+
|                       SLEEP                        |
|        (Offline Vosk Wake-Word Only)               |
+----------------------------------------------------+
```

### 1. ACTIVE (Continuous Listening & Command Routing)
- Continuously listens for commands without needing wake words between phrases.
- **Phrases & Actions**:
  - Say `"pause"` &rarr; Transitions to **PAUSED**. Plays pause chime and speaks *"Paused."*. If an active permission confirmation popup is currently open, it is automatically denied.
  - Say `"go to sleep"` / `"sleep"` &rarr; Transitions to **SLEEP**. Plays sleep chime.
  - Say `"stop listening"` &rarr; Turns Voice feature completely OFF.
  - Regular commands (e.g., `"what time is it"`, `"hello"`, permission confirmations `"yes"`/`"no"`) execute normally through `CommandRouter`.
- **Inactivity Timeout**: If no speech is heard for `session_timeout_seconds` (default: 60s), automatically transitions to **SLEEP**.

### 2. PAUSED (Offline Restricted Standby)
- **Privacy & Safety Guarantee**:
  - Zero audio is sent to Google.
  - No commands are executed (`CommandRouter` rejects all commands).
- **Offline Restricted Recognition**:
  - Listens strictly through local Vosk offline recognizer with restricted grammar (`["h p resume", "hp resume", "h p sleep", "hp sleep", "[unk]"]`).
  - Say `"HP resume"` &rarr; Transitions to **ACTIVE**. Plays resume chime and speaks *"Resumed."*.
  - Say `"HP sleep"` &rarr; Transitions to **SLEEP**. Plays sleep chime.
- **Pause Timeout**: If paused for longer than `pause_timeout_minutes` (default: 10 minutes), automatically transitions to **SLEEP**.

### 3. SLEEP (Offline Wake-Phrase Detection)
- Listens only for the wake phrase `"wake up HP"` using the local Vosk offline recognizer.
- Zero audio is sent online.
- Say `"wake up HP"` &rarr; Transitions to **ACTIVE**. Plays start chime and begins continuous session.

---

## Audio Feedback & Status Indicators

- **Distinct Audio Cues**:
  - **Session Start**: High chime (1200 Hz).
  - **Pause**: Descending two-tone chime (850 Hz &rarr; 600 Hz).
  - **Resume**: Ascending two-tone chime (600 Hz &rarr; 850 Hz).
  - **Sleep**: Low chime (450 Hz).
- **Dynamic Tray Tooltip**:
  - Shows current voice state in real time:
    - `HP Assistant - ON [Voice: Active]`
    - `HP Assistant - ON [Voice: Paused]`
    - `HP Assistant - ON [Voice: Sleeping]`
    - `HP Assistant - ON [Voice: OFF]`
    - `HP Assistant - OFF`
- **Audit Logging**:
  - Every state transition is recorded in `logs/audit.log` with timestamp, from-state, to-state, and trigger reason:
    ```text
    2026-11-09 19:45:42 | ACTION: voice_state_transition | LEVEL: safe | RESULT: Active->Paused | DETAILS: from=Active, to=Paused, reason=user_pause
    ```

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

## How to Test the Voice State Transitions

1. **Launch the Assistant**:
   ```powershell
   python main.py
   ```
2. **Turn on Master and Voice**:
   - Right-click red tray icon &rarr; **Turn ON** (icon turns green).
   - Right-click tray icon &rarr; **Voice: OFF** (turns into `Voice: ON` with a checkmark; tooltip shows `HP Assistant - ON [Voice: Sleeping]`).

3. **Transition 1: SLEEP &rarr; ACTIVE**:
   - Say:
     > *"Wake up HP"*
   - **Feedback**: High start chime (1200 Hz).
   - **Tooltip**: Updates to `HP Assistant - ON [Voice: Active]`.
   - Assistant listens continuously for commands.

4. **Transition 2: ACTIVE &rarr; PAUSED**:
   - While in active session, say:
     > *"Pause"*
   - **Feedback**: Descending pause chime (850 Hz &rarr; 600 Hz), assistant speaks *"Paused."*.
   - **Tooltip**: Updates to `HP Assistant - ON [Voice: Paused]`.
   - **Privacy Guard**: Microphone is kept open locally for offline Vosk only; no commands run and zero audio is sent online.
   - If a permission confirmation popup was waiting, it is automatically denied.

5. **Transition 3: PAUSED &rarr; ACTIVE**:
   - While paused, say:
     > *"HP resume"*
   - **Feedback**: Ascending resume chime (600 Hz &rarr; 850 Hz), assistant speaks *"Resumed."*.
   - **Tooltip**: Updates to `HP Assistant - ON [Voice: Active]`.

6. **Transition 4: PAUSED &rarr; SLEEP**:
   - From paused state, say:
     > *"HP sleep"*
   - **Feedback**: Low sleep chime (450 Hz), assistant speaks *"Going to sleep."*.
   - **Tooltip**: Updates to `HP Assistant - ON [Voice: Sleeping]`.

7. **Transition 5: ACTIVE &rarr; SLEEP**:
   - While in active session, say:
     > *"Go to sleep"* (or *"sleep"*)
   - **Feedback**: Low sleep chime (450 Hz), assistant speaks *"Going to sleep."*.
   - **Tooltip**: Updates to `HP Assistant - ON [Voice: Sleeping]`.

8. **Transition 6: Timeouts**:
   - In **ACTIVE** state: Remain silent for 60 seconds &rarr; low sleep chime plays, transitions to **SLEEP**.
   - In **PAUSED** state: Inactivity for 10 minutes &rarr; low sleep chime plays, transitions to **SLEEP**.

---

## Running Tests

Execute the full pytest suite (53 tests):
```powershell
pytest -v
```

To run the voice module tests specifically (19 tests):
```powershell
pytest tests/test_voice_module.py -v
```
