"""
Unit tests for HP Assistant Permission System (core/permissions.py).
Verifies:
- safe actions run immediately
- blocked actions are always denied
- confirm actions ask first
- unknown actions strictly default to confirm (never safe)
- timeout auto-denies
- only one confirmation active at a time (extra requests denied, not queued)
- voice confirm hook accepts/denies
- audit logging
"""

import os
import tempfile
import time
import pytest

from core.permissions import PermissionManager


@pytest.fixture
def temp_audit_file():
    """Provides a temporary audit log path and cleans up afterwards."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test_audit.log")


@pytest.fixture
def perm_manager(temp_audit_file):
    """Provides a fresh PermissionManager instance with temporary audit log."""
    config = {
        "permissions": {
            "confirmation_timeout_seconds": 1.0,
            "audit_log_file": temp_audit_file,
            "safe": ["volume", "scroll", "screenshot", "open_app", "media_play_pause", "window_switch", "cursor_move", "click"],
            "confirm": ["close_window", "shutdown", "restart", "delete_file", "type_text", "run_command", "send_message", "cut", "drag_drop"],
            "blocked": ["format_drive", "registry_edit", "disable_security", "install_software"],
        }
    }
    return PermissionManager(config=config)


def test_safe_actions_run_immediately(perm_manager: PermissionManager, temp_audit_file: str) -> None:
    """Safe actions return True immediately without opening confirmation dialogs."""
    safe_samples = ["volume", "scroll", "screenshot", "open_app", "click"]
    for action in safe_samples:
        assert perm_manager.get_level(action) == "safe"
        assert perm_manager.request(action) is True

    # Check audit log
    with open(temp_audit_file, "r", encoding="utf-8") as f:
        log_content = f.read()

    assert "ACTION: volume | LEVEL: safe | RESULT: allowed" in log_content
    assert "ACTION: click | LEVEL: safe | RESULT: allowed" in log_content


def test_blocked_actions_always_denied(perm_manager: PermissionManager, temp_audit_file: str) -> None:
    """Blocked actions return False immediately and are never executed."""
    blocked_samples = ["format_drive", "registry_edit", "disable_security", "install_software"]
    for action in blocked_samples:
        assert perm_manager.get_level(action) == "blocked"
        assert perm_manager.request(action, details="Test malicious intent") is False

    # Check audit log
    with open(temp_audit_file, "r", encoding="utf-8") as f:
        log_content = f.read()

    assert "ACTION: format_drive | LEVEL: blocked | RESULT: blocked" in log_content
    assert "ACTION: registry_edit | LEVEL: blocked | RESULT: blocked" in log_content


def test_confirm_action_asks_and_allows(perm_manager: PermissionManager, temp_audit_file: str) -> None:
    """Confirm actions ask user; if allowed, return True."""
    # Mock UI approval
    perm_manager._ui_confirm_hook = lambda act, det, timeout: (True, "allowed")

    assert perm_manager.get_level("shutdown") == "confirm"
    result = perm_manager.request("shutdown", details="User commanded shutdown")
    assert result is True

    with open(temp_audit_file, "r", encoding="utf-8") as f:
        log_content = f.read()

    assert "ACTION: shutdown | LEVEL: confirm | RESULT: allowed" in log_content


def test_confirm_action_asks_and_denies(perm_manager: PermissionManager, temp_audit_file: str) -> None:
    """Confirm actions ask user; if denied, return False."""
    perm_manager._ui_confirm_hook = lambda act, det, timeout: (False, "denied")

    assert perm_manager.get_level("delete_file") == "confirm"
    result = perm_manager.request("delete_file", details="sensitive_doc.pdf")
    assert result is False

    with open(temp_audit_file, "r", encoding="utf-8") as f:
        log_content = f.read()

    assert "ACTION: delete_file | LEVEL: confirm | RESULT: denied" in log_content


def test_unknown_action_strictly_defaults_to_confirm(perm_manager: PermissionManager, temp_audit_file: str) -> None:
    """Any action NOT listed in config must default to 'confirm', NEVER 'safe'."""
    unknown_actions = ["launch_missile", "send_crypto", "random_unregistered_action"]
    for action in unknown_actions:
        level = perm_manager.get_level(action)
        assert level == "confirm"
        assert level != "safe"

    # When mock denies, returns False
    perm_manager._ui_confirm_hook = lambda act, det, timeout: (False, "denied")
    assert perm_manager.request("launch_missile") is False

    with open(temp_audit_file, "r", encoding="utf-8") as f:
        log_content = f.read()

    assert "ACTION: launch_missile | LEVEL: confirm | RESULT: denied" in log_content


def test_timeout_auto_denies(perm_manager: PermissionManager, temp_audit_file: str) -> None:
    """When confirmation times out with no user answer, it auto-denies."""
    # Test with very short timeout for fast execution
    perm_manager.timeout_seconds = 0.15
    # Use real Tkinter popup with short timeout to test real timer
    result = perm_manager.request("run_command", details="powershell -Command Get-Process")
    assert result is False

    with open(temp_audit_file, "r", encoding="utf-8") as f:
        log_content = f.read()

    assert "ACTION: run_command | LEVEL: confirm | RESULT: timed out" in log_content


def test_only_one_confirmation_at_a_time_extra_denied(perm_manager: PermissionManager, temp_audit_file: str) -> None:
    """Extra confirmation requests while one is active must be denied immediately, not queued."""
    import threading

    results = []

    def slow_request():
        # Holds active confirmation for 0.4 seconds
        def mock_slow_confirm(act, det, to):
            time.sleep(0.3)
            return (True, "allowed")

        perm_manager._ui_confirm_hook = mock_slow_confirm
        res = perm_manager.request("shutdown")
        results.append(("first", res))

    t = threading.Thread(target=slow_request)
    t.start()

    # Wait until first confirmation is marked active
    time.sleep(0.08)
    assert perm_manager.is_confirmation_active() is True

    # Second request while first is active must be rejected immediately!
    second_res = perm_manager.request("delete_file", details="Extra concurrent request")
    assert second_res is False
    results.append(("second", second_res))

    t.join()

    # Verify first succeeded, second denied immediately
    assert ("first", True) in results
    assert ("second", False) in results

    with open(temp_audit_file, "r", encoding="utf-8") as f:
        log_content = f.read()

    assert "ACTION: delete_file | LEVEL: confirm | RESULT: denied | DETAILS: Extra concurrent request (Denied: confirmation already in progress)" in log_content


def test_voice_confirm_hook(perm_manager: PermissionManager) -> None:
    """Voice confirm hook allows answering an active popup via external speech trigger."""
    import threading

    perm_manager.timeout_seconds = 1.0

    # Test voice accept (True)
    def run_req_allow():
        return perm_manager.request("close_window")

    t1 = threading.Thread(target=run_req_allow)
    t1.start()

    time.sleep(0.08)
    # Voice accepts
    hook_result = perm_manager.voice_confirm(True)
    assert hook_result is True

    t1.join(2.0)
    assert perm_manager.is_confirmation_active() is False

    # Test voice confirm when no confirmation active returns False
    assert perm_manager.voice_confirm(True) is False

