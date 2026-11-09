"""
Permission and security gateway for HP Assistant.
Enforces safe, confirm, and blocked permission tiers for all assistant actions.
Includes an audit log and Tkinter-based confirmation dialog with voice hook.
"""

from datetime import datetime
import logging
import os
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .config import load_config


class _TkConfirmationRunner(threading.Thread):
    """
    Dedicated GUI daemon thread managing Tkinter root and Toplevel confirmation dialogs.
    Avoids multi-threaded Tkinter lifecycle issues and Tcl_AsyncDelete warnings.
    """

    def __init__(self) -> None:
        super().__init__(name="HP_Assistant_TkRunner", daemon=True)
        self.task_queue: queue.Queue = queue.Queue()
        self.root: Optional[Any] = None
        self._ready_event = threading.Event()

    def run(self) -> None:
        import tkinter as tk

        try:
            self.root = tk.Tk()
            self.root.withdraw()  # Hidden parent window
            self._ready_event.set()

            def poll() -> None:
                while not self.task_queue.empty():
                    try:
                        task = self.task_queue.get_nowait()
                        task(self.root)
                    except queue.Empty:
                        break
                    except Exception:
                        pass
                if self.root:
                    try:
                        self.root.after(30, poll)
                    except Exception:
                        pass

            self.root.after(30, poll)
            self.root.mainloop()
        except Exception:
            self._ready_event.set()

    def submit_task(self, task: Callable[[Any], None]) -> None:
        self.task_queue.put(task)

    def ensure_started(self) -> None:
        if not self.is_alive():
            self.start()
            self._ready_event.wait(timeout=2.0)


class PermissionManager:
    """
    Central permission gateway.
    Every action in every module must request permission through this manager.
    """

    DEFAULT_SAFE: List[str] = [
        "volume",
        "scroll",
        "screenshot",
        "open_app",
        "media_play_pause",
        "window_switch",
        "cursor_move",
        "click",
    ]

    DEFAULT_CONFIRM: List[str] = [
        "close_window",
        "shutdown",
        "restart",
        "delete_file",
        "type_text",
        "run_command",
        "send_message",
        "cut",
        "drag_drop",
    ]

    DEFAULT_BLOCKED: List[str] = [
        "format_drive",
        "registry_edit",
        "disable_security",
        "install_software",
    ]

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._logger = logger or logging.getLogger("HP_Assistant.Permissions")
        self._config = config or load_config()

        # Extract permission rules
        perm_config = self._config.get("permissions", {})
        self.safe_actions: Set[str] = set(
            a.lower() for a in perm_config.get("safe", self.DEFAULT_SAFE)
        )
        self.confirm_actions: Set[str] = set(
            a.lower() for a in perm_config.get("confirm", self.DEFAULT_CONFIRM)
        )
        self.blocked_actions: Set[str] = set(
            a.lower() for a in perm_config.get("blocked", self.DEFAULT_BLOCKED)
        )

        self.timeout_seconds: float = float(
            perm_config.get("confirmation_timeout_seconds", 10)
        )
        self.audit_log_path: str = perm_config.get(
            "audit_log_file", "logs/audit.log"
        )

        # Concurrency & Confirmation State
        self._lock = threading.Lock()
        self._active_confirmation = False
        self._voice_response_event = threading.Event()
        self._voice_response_value: Optional[bool] = None

        # Dedicated GUI runner
        self._tk_runner: Optional[_TkConfirmationRunner] = None

        # Optional UI hook for headless unit testing
        self._ui_confirm_hook: Optional[
            Callable[[str, Optional[str], float], Tuple[bool, str]]
        ] = None

        # Ensure logs directory exists
        log_dir = os.path.dirname(self.audit_log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

    def _ensure_tk_runner(self) -> _TkConfirmationRunner:
        """Lazily initialize the background Tkinter daemon thread."""
        with self._lock:
            if self._tk_runner is None or not self._tk_runner.is_alive():
                self._tk_runner = _TkConfirmationRunner()
                self._tk_runner.ensure_started()
            return self._tk_runner

    def reload_config(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Reload permission settings from provided dictionary or config.json."""
        self._config = config or load_config()
        perm_config = self._config.get("permissions", {})
        self.safe_actions = set(
            a.lower() for a in perm_config.get("safe", self.DEFAULT_SAFE)
        )
        self.confirm_actions = set(
            a.lower() for a in perm_config.get("confirm", self.DEFAULT_CONFIRM)
        )
        self.blocked_actions = set(
            a.lower() for a in perm_config.get("blocked", self.DEFAULT_BLOCKED)
        )
        self.timeout_seconds = float(
            perm_config.get("confirmation_timeout_seconds", 10)
        )
        self.audit_log_path = perm_config.get("audit_log_file", "logs/audit.log")

    def get_level(self, action_name: str) -> str:
        """
        Determine risk tier for an action: 'safe', 'confirm', or 'blocked'.
        Any unlisted action strictly defaults to 'confirm', never 'safe'.
        """
        act = action_name.strip().lower()
        if act in self.blocked_actions:
            return "blocked"
        if act in self.safe_actions:
            return "safe"
        if act in self.confirm_actions:
            return "confirm"
        # Unknown action strictly defaults to confirm
        return "confirm"

    def is_confirmation_active(self) -> bool:
        """Returns True if a confirmation popup is currently awaiting user action."""
        with self._lock:
            return self._active_confirmation

    def voice_confirm(self, approved: bool) -> bool:
        """
        External hook allowing voice module (in later stages) to accept or deny
        an active confirmation request ("yes/confirm" -> True, "no/cancel" -> False).
        Returns True if an active confirmation was resolved, False otherwise.
        """
        with self._lock:
            if not self._active_confirmation:
                return False
            self._voice_response_value = approved
            self._voice_response_event.set()
            return True

    def _write_audit_log(
        self, action: str, level: str, result: str, details: Optional[str] = None
    ) -> None:
        """
        Write a structured audit entry with a timestamp to the audit log and logger.
        Result is one of: 'allowed', 'denied', 'blocked', 'timed out'.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        details_str = details if details is not None else "None"
        line = f"{timestamp} | ACTION: {action} | LEVEL: {level} | RESULT: {result} | DETAILS: {details_str}\n"

        try:
            log_dir = os.path.dirname(self.audit_log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            self._logger.error("Failed to write to audit log file %s: %s", self.audit_log_path, e)

        self._logger.info(
            "[AUDIT] %s | ACTION: %s | LEVEL: %s | RESULT: %s | DETAILS: %s",
            timestamp,
            action,
            level,
            result,
            details_str,
        )

    def _show_tkinter_popup(
        self, action_name: str, details: Optional[str], timeout: float
    ) -> Tuple[bool, str]:
        """
        Display an always-on-top Tkinter confirmation dialog on the dedicated runner.
        Returns (decision: bool, result_status: str).
        """
        import tkinter as tk

        runner = self._ensure_tk_runner()
        done_event = threading.Event()
        res = {"decision": False, "status": "denied"}
        deadline = time.time() + timeout

        def _create_dialog(root: Any) -> None:
            try:
                top = tk.Toplevel(root)
                top.title("HP Assistant - Permission Required")
                top.attributes("-topmost", True)
                top.geometry("400x200")
                top.resizable(False, False)
                top.configure(bg="#1E1E2E")

                # Center dialog if supported
                try:
                    top.eval("tk::PlaceWindow . center")
                except Exception:
                    pass

                # Header
                header_lbl = tk.Label(
                    top,
                    text="Action Requires Approval",
                    font=("Segoe UI", 12, "bold"),
                    fg="#F8FAFC",
                    bg="#1E1E2E",
                )
                header_lbl.pack(pady=(12, 4))

                # Action and details
                action_text = f"Action: {action_name}"
                if details:
                    action_text += f"\nDetails: {details}"

                info_lbl = tk.Label(
                    top,
                    text=action_text,
                    font=("Segoe UI", 10),
                    fg="#CBD5E1",
                    bg="#1E1E2E",
                    wraplength=360,
                    justify="center",
                )
                info_lbl.pack(pady=4)

                # Countdown label
                timer_lbl = tk.Label(
                    top,
                    text=f"Auto-denying in {int(timeout)}s...",
                    font=("Segoe UI", 9, "italic"),
                    fg="#94A3B8",
                    bg="#1E1E2E",
                )
                timer_lbl.pack(pady=4)

                def on_allow() -> None:
                    res["decision"] = True
                    res["status"] = "allowed"
                    try:
                        top.destroy()
                    except Exception:
                        pass
                    done_event.set()

                def on_deny() -> None:
                    res["decision"] = False
                    res["status"] = "denied"
                    try:
                        top.destroy()
                    except Exception:
                        pass
                    done_event.set()

                top.protocol("WM_DELETE_WINDOW", on_deny)

                # Buttons container
                btn_frame = tk.Frame(top, bg="#1E1E2E")
                btn_frame.pack(pady=(8, 12))

                allow_btn = tk.Button(
                    btn_frame,
                    text="Allow",
                    font=("Segoe UI", 10, "bold"),
                    bg="#22C55E",
                    fg="#FFFFFF",
                    activebackground="#16A34A",
                    activeforeground="#FFFFFF",
                    width=10,
                    relief="flat",
                    cursor="hand2",
                    command=on_allow,
                )
                allow_btn.pack(side="left", padx=10)

                deny_btn = tk.Button(
                    btn_frame,
                    text="Deny",
                    font=("Segoe UI", 10, "bold"),
                    bg="#EF4444",
                    fg="#FFFFFF",
                    activebackground="#DC2626",
                    activeforeground="#FFFFFF",
                    width=10,
                    relief="flat",
                    cursor="hand2",
                    command=on_deny,
                )
                deny_btn.pack(side="right", padx=10)

                # Polling loop for voice responses and timeout
                def poll_state() -> None:
                    # 1. Voice hook check
                    if self._voice_response_event.is_set():
                        res["decision"] = bool(self._voice_response_value)
                        res["status"] = "allowed" if res["decision"] else "denied"
                        try:
                            top.destroy()
                        except Exception:
                            pass
                        done_event.set()
                        return

                    # 2. Timeout check
                    now = time.time()
                    if now >= deadline:
                        res["decision"] = False
                        res["status"] = "timed out"
                        try:
                            top.destroy()
                        except Exception:
                            pass
                        done_event.set()
                        return

                    # Update remaining seconds text
                    rem = max(0, int(deadline - now) + 1)
                    try:
                        timer_lbl.config(text=f"Auto-denying in {rem}s...")
                        top.after(30, poll_state)
                    except Exception:
                        pass

                top.after(30, poll_state)
            except Exception as e:
                self._logger.error("Error creating Tkinter confirmation dialog: %s", e)
                res["decision"] = False
                res["status"] = "denied"
                done_event.set()

        runner.submit_task(_create_dialog)
        done_event.wait(timeout + 2.0)
        return res["decision"], res["status"]

    def request(self, action_name: str, details: Optional[str] = None) -> bool:
        """
        Central security gateway.
        Returns True if action is allowed, False if denied/blocked/timed out.
        """
        level = self.get_level(action_name)

        # 1. Safe Tier: runs immediately
        if level == "safe":
            self._write_audit_log(action_name, level, "allowed", details)
            return True

        # 2. Blocked Tier: always denied immediately
        if level == "blocked":
            self._write_audit_log(action_name, level, "blocked", details)
            return False

        # 3. Confirm Tier: requires explicit user confirmation
        # Only one confirmation at a time; extra requests are denied, not queued.
        with self._lock:
            if self._active_confirmation:
                self._write_audit_log(
                    action_name,
                    level,
                    "denied",
                    f"{details or 'None'} (Denied: confirmation already in progress)",
                )
                return False
            self._active_confirmation = True
            self._voice_response_event.clear()
            self._voice_response_value = None

        try:
            if self._ui_confirm_hook is not None:
                decision, status = self._ui_confirm_hook(
                    action_name, details, self.timeout_seconds
                )
            else:
                decision, status = self._show_tkinter_popup(
                    action_name, details, self.timeout_seconds
                )

            self._write_audit_log(action_name, level, status, details)
            return decision
        finally:
            with self._lock:
                self._active_confirmation = False
                self._voice_response_event.clear()
                self._voice_response_value = None


# Default global gateway singleton
permissions = PermissionManager()
