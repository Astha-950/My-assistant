# HP Assistant - Stage 1.5

HP Assistant is a modular, privacy-first desktop assistant designed for Windows.

This repository represents **Stage 1.5: Feature Toggles & Permission System** (built on top of Stage 1: Project Skeleton & Master Toggle). It provides the core application foundation, master and per-feature ON/OFF toggles, a central security permission gateway, system tray integration with dynamic visual states, and complete audit logging.

> **Stage 1.5 Scope:** This stage introduces granular feature switches (`voice` and `gestures`) and an action permission gateway. Voice recognition, camera capture, and gesture detection implementations will be introduced in subsequent stages.

---

## Architecture & Project Structure

```text
My_assistant/
│
├── main.py                   # Application entry point and lifecycle orchestration
├── config.json               # Configuration (hotkeys, logging, permission mappings)
├── requirements.txt          # Python dependencies
├── README.md                 # Setup, usage, and developer documentation
├── .gitignore                # Git exclusions (venv, logs, cache, credentials)
│
├── core/
│   ├── __init__.py           # Package exports
│   ├── config.py             # Safe configuration loader and logging setup
│   ├── controller.py         # Thread-safe master controller and per-feature toggles
│   ├── permissions.py        # Central permission gateway, Tkinter popup, & audit log
│   └── tray.py               # System tray icon, right-click menu, checkmarks, & toasts
│
├── modules/
│   └── __init__.py           # Placeholder for modules added in future stages
│
└── tests/
    ├── __init__.py
    ├── test_config.py        # Configuration unit tests
    ├── test_controller.py    # Master controller state, idempotency, and lifecycle tests
    ├── test_feature_toggles.py # Feature toggle hierarchy (Voice/Gestures) tests
    └── test_permissions.py   # Security tiers, popup, timeout, voice hook, and audit tests
```

---

## Stage 1.5 Additions

### 1. Per-Feature Toggles (`core/controller.py`)
- **Independent Switches**: `voice` and `gestures` operate as separate switches under the master switch.
- **Hierarchy Rules**:
  - Voice and Gestures can **only** run when the Master switch is **ON**.
  - Turning the Master switch **OFF** forcefully turns both Voice and Gestures **OFF** and releases all their module resources.
  - Everything defaults to **OFF** on every application launch.
- **Module Feature Registration**:
  Modules can register under specific features:
  ```python
  controller.register_module(my_voice_module, feature="voice")
  controller.register_module(my_gesture_module, feature="gestures")
  controller.register_module(my_core_module, feature=None)
  ```
- **System Tray Menu**:
  Right-click context menu features:
  - `Turn ON` / `Turn OFF` (Master switch)
  - `Voice: ON/OFF` (with dynamic checkmark)
  - `Gestures: ON/OFF` (with dynamic checkmark)
  - `Quit completely`

---

### 2. Central Permission Gateway (`core/permissions.py`)
All future modules and actions **MUST** request authorization via the central gateway:
```python
from core.permissions import permissions

if permissions.request("screenshot", details="Active window capture"):
    # execute action
```

#### Three Risk Tiers:
| Tier | Behavior | Default Actions |
|---|---|---|
| **`safe`** | Runs immediately without prompting. | `volume`, `scroll`, `screenshot`, `open_app`, `media_play_pause`, `window_switch`, `cursor_move`, `click` |
| **`confirm`** | Asks user first via popup window or voice confirmation. | `close_window`, `shutdown`, `restart`, `delete_file`, `type_text`, `run_command`, `send_message`, `cut`, `drag_drop` |
| **`blocked`** | Always denied automatically. Never executed. | `format_drive`, `registry_edit`, `disable_security`, `install_software` |

> **Fail-Safe Guarantee:** Any action **NOT** listed in `config.json` strictly defaults to **`confirm`**, never `safe`.

#### Confirmation Dialog:
- **Always-on-Top Popup**: Lightweight Tkinter popup displaying the action name and details with **Allow** and **Deny** buttons.
- **Auto-Deny Timeout**: Configurable timeout (default: 10 seconds). Automatically denies if no answer is given.
- **Single Confirmation Concurrency**: Only one confirmation popup can be active at a time; extra concurrent requests are denied immediately, never queued.
- **Voice Confirmation Hook**: `permissions.voice_confirm(True/False)` allows future voice recognition modules to accept ("yes/confirm") or reject active prompts hands-free.

---

### 3. Audit Log (`logs/audit.log`)
Every permission request is recorded in `logs/audit.log` (ignored by Git):
```text
2026-11-09 17:50:00 | ACTION: volume | LEVEL: safe | RESULT: allowed | DETAILS: None
2026-11-09 17:50:05 | ACTION: shutdown | LEVEL: confirm | RESULT: allowed | DETAILS: User requested full shutdown
2026-11-09 17:50:10 | ACTION: format_drive | LEVEL: blocked | RESULT: blocked | DETAILS: Disk C:
2026-11-09 17:50:20 | ACTION: delete_file | LEVEL: confirm | RESULT: timed out | DETAILS: report.docx
```
Possible results: `allowed`, `denied`, `blocked`, `timed out`.

---

## Configuration (`config.json`)

```json
{
  "app_name": "HP Assistant",
  "version": "1.5.0",
  "hotkey_enabled": false,
  "hotkey": "ctrl+alt+h",
  "beep_on_toggle": true,
  "toast_on_toggle": true,
  "log_file": "logs/assistant.log",
  "log_level": "INFO",
  "permissions": {
    "confirmation_timeout_seconds": 10,
    "audit_log_file": "logs/audit.log",
    "safe": [
      "volume",
      "scroll",
      "screenshot",
      "open_app",
      "media_play_pause",
      "window_switch",
      "cursor_move",
      "click"
    ],
    "confirm": [
      "close_window",
      "shutdown",
      "restart",
      "delete_file",
      "type_text",
      "run_command",
      "send_message",
      "cut",
      "drag_drop"
    ],
    "blocked": [
      "format_drive",
      "registry_edit",
      "disable_security",
      "install_software"
    ]
  }
}
```

---

## How to Run

Launch the application:
```powershell
python main.py
```

1. Look for the **HP Assistant** red circle icon in your Windows Taskbar System Tray.
2. **Right-click** the tray icon to view controls:
   - Click **Turn ON** &rarr; Master turns **Green**, general modules activate.
   - Click **Voice: OFF** &rarr; Toggles Voice feature ON (checkmark appears).
   - Click **Gestures: OFF** &rarr; Toggles Gestures feature ON (checkmark appears).
   - Click **Turn OFF** &rarr; Turns Master OFF, automatically forcing Voice and Gestures OFF and releasing all resources.
   - Click **Quit completely** &rarr; Shuts down all features and cleanly terminates the process.

---

## Running Tests

Execute the comprehensive pytest test suite (34 tests):
```powershell
pytest -v
```

Run specific test modules:
```powershell
pytest tests/test_feature_toggles.py -v
pytest tests/test_permissions.py -v
```

---

## Next Steps: Roadmap
- **Stage 2**: Audio input, wake-word detection, and voice processing.
- **Stage 3**: Camera capture and computer vision pipeline.
- **Stage 4**: Real-time gesture recognition.
- **Stage 5**: Multimodal fusion and autonomous action workflows.
