# HP Assistant - Stage 1

HP Assistant is a modular, privacy-first desktop assistant designed for Windows.

This repository represents **Stage 1: Project Skeleton & Master Toggle**. It provides the core application foundation, an idempotent and thread-safe master ON/OFF switch, system tray integration with dynamic visual states, resource management, and configuration capabilities.

> **Stage 1 Scope:** This stage strictly implements the skeleton and master switch. Voice, camera, and gesture detection will be introduced in subsequent stages as registered modules.

---

## Architecture & Project Structure

```text
My_assistant/
│
├── main.py                   # Application entry point and lifecycle orchestration
├── config.json               # User configuration (hotkeys, logging, audio/toast settings)
├── requirements.txt          # Python dependencies
├── README.md                 # Setup, usage, and developer documentation
├── .gitignore                # Git exclusions (venv, logs, cache, credentials)
│
├── core/
│   ├── __init__.py           # Package exports
│   ├── config.py             # Safe configuration loader and logging setup
│   ├── controller.py         # Thread-safe master controller and BaseModule definition
│   └── tray.py               # System tray icon, right-click menu, and notifications
│
├── modules/
│   └── __init__.py           # Placeholder for modules added in future stages
│
└── tests/
    ├── __init__.py
    ├── test_config.py        # Configuration unit tests
    └── test_controller.py    # Controller state, idempotency, lifecycle, and thread-safety tests
```

---

## Core Features (Stage 1)

### 1. Master Controller (`core/controller.py`)
- **Default OFF State**: The application strictly initializes with state `OFF` upon startup.
- **Module Lifecycle Interface**: Modules subclass `BaseModule` and implement `start()` and `stop()`.
- **Atomic State Transitions**:
  - `turn_on()` starts all registered modules in order and sets state to `ON`.
  - `turn_off()` calls `stop()` on all registered modules in reverse order and confirms all resources are released.
- **Idempotency**: Repeated calls to `turn_on()` or `turn_off()` are safe no-ops and will not duplicate module starts or stops.
- **Thread Safety**: Protected by re-entrant thread locks (`threading.RLock`) for concurrent interactions (tray clicks, hotkeys, background threads).
- **Includes Dummy Test Module**: `DummyModule` is included and registered by default to verify the lifecycle.

### 2. System Tray Integration (`core/tray.py`)
- Built using **pystray** and **Pillow**.
- **Dynamic Status Icons**:
  - 🟢 **Green Icon**: Master state is **ON**.
  - 🔴 **Red Icon**: Master state is **OFF**.
- **Right-Click Context Menu**:
  - `Turn ON`: Activates the controller and starts modules.
  - `Turn OFF`: Deactivates the controller and stops modules.
  - `Quit completely`: Safely turns off the controller, releases all module resources, removes tray icons, and exits the process.
- **Feedback**:
  - **Beep**: Short high-frequency beep on ON (1000 Hz), lower-frequency beep on OFF (600 Hz).
  - **Toast**: Native Windows toast notification indicating the new state.

### 3. Optional Global Hotkey (`main.py`)
- Default combination: `Ctrl+Alt+H` (customizable in `config.json`).
- Disabled by default (`"hotkey_enabled": false`).
- **Zero Overhead / Privacy Guarantee**: When state is OFF and `hotkey_enabled` is false, no keyboard or mouse hooks are registered in the operating system.

### 4. Logging & Diagnostics (`logs/assistant.log`)
- Configured via `core/config.py`.
- Logs all state changes and lifecycle events with timestamps:
  ```text
  2026-11-09 17:35:13 [INFO] [HP_Assistant] [EVENT] Controller initialized. Master state: OFF
  2026-11-09 17:35:13 [INFO] [HP_Assistant] [EVENT] Master State changed: ON
  2026-11-09 17:35:13 [INFO] [HP_Assistant] [EVENT] Master State changed: OFF | All module resources released: True
  ```
- The `logs/` directory is automatically ignored by Git.

---

## Prerequisites

- **Operating System**: Windows 10 or Windows 11
- **Python**: Python 3.10 or higher

---

## Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Astha-950/My-assistant.git
   cd My-assistant
   ```

2. **Create and activate a virtual environment**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

---

## Configuration (`config.json`)

The default configuration file is automatically read from `config.json`:

```json
{
  "app_name": "HP Assistant",
  "version": "1.0.0",
  "hotkey_enabled": false,
  "hotkey": "ctrl+alt+h",
  "beep_on_toggle": true,
  "toast_on_toggle": true,
  "log_file": "logs/assistant.log",
  "log_level": "INFO"
}
```

| Setting | Type | Default | Description |
|---|---|---|---|
| `app_name` | string | `"HP Assistant"` | Application name displayed in tray and toasts. |
| `version` | string | `"1.0.0"` | Current version. |
| `hotkey_enabled` | boolean | `false` | When `true`, registers the global hotkey. When `false`, zero keyboard hooks exist. |
| `hotkey` | string | `"ctrl+alt+h"` | Key combination for global toggle. |
| `beep_on_toggle` | boolean | `true` | Plays a distinct audio beep when toggled. |
| `toast_on_toggle` | boolean | `true` | Displays a Windows notification balloon/toast on toggle. |
| `log_file` | string | `"logs/assistant.log"` | Output path for persistent log file. |
| `log_level` | string | `"INFO"` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

---

## How to Run

Launch the application:

```powershell
python main.py
```

1. Look for the **HP Assistant** red circle icon in your Windows Taskbar System Tray (bottom right near the clock).
2. **Right-click** the tray icon to view the menu:
   - Click **Turn ON** &rarr; The icon turns **Green**, a high beep sounds, and registered modules start.
   - Click **Turn OFF** &rarr; The icon turns **Red**, a low beep sounds, and all modules are stopped.
   - Click **Quit completely** &rarr; Safely turns off the assistant, releases all module resources, and exits the application.

---

## Running Tests

Execute the comprehensive pytest test suite:

```powershell
pytest -v
```

Or run the controller tests specifically:

```powershell
pytest tests/test_controller.py -v
```

### Test Coverage Highlights
- Default `OFF` state on startup
- Toggling between `ON` and `OFF`
- Idempotency for repeated `turn_on()` and `turn_off()` calls
- Module registration, starting, stopping, and resource release confirmation
- Multiple registered modules execution order and reverse stop order
- Thread safety under concurrent toggles
- Timestamped event logging

---

## Future Stages Roadmap

- **Stage 2**: Audio input and local/cloud voice processing module.
- **Stage 3**: Camera and vision analysis module.
- **Stage 4**: Real-time gesture recognition module.
- **Stage 5**: Unified multimodal fusion and workflow actions.

All upcoming modules will plug directly into `core/controller.py` using `BaseModule`.
