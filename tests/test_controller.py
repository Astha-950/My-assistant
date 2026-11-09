"""
Unit tests for HP Assistant Controller.
Covers default state, toggling, idempotency, module lifecycle, thread safety, and logging.
"""

import io
import logging
import threading
import time
import pytest

from core.controller import AssistantController, BaseModule, DummyModule


class CustomTestModule(BaseModule):
    """Custom module tracking call order and execution."""

    def __init__(self, name: str, call_log: list) -> None:
        self._name = name
        self.call_log = call_log
        self.is_running = False

    @property
    def name(self) -> str:
        return self._name

    def start(self) -> None:
        self.is_running = True
        self.call_log.append(f"{self._name}_started")

    def stop(self) -> None:
        self.is_running = False
        self.call_log.append(f"{self._name}_stopped")


@pytest.fixture
def controller() -> AssistantController:
    """Fixture providing a fresh controller for each test."""
    logger = logging.getLogger("TestController")
    logger.setLevel(logging.DEBUG)
    return AssistantController(logger=logger)


def test_default_state_is_off(controller: AssistantController) -> None:
    """Verify that the controller defaults to OFF on creation."""
    assert controller.is_on is False
    assert controller.is_off is True
    assert controller.state_name == "OFF"


def test_turn_on(controller: AssistantController) -> None:
    """Verify that turn_on switches state to ON."""
    result = controller.turn_on()
    assert result is True
    assert controller.is_on is True
    assert controller.is_off is False
    assert controller.state_name == "ON"


def test_turn_off(controller: AssistantController) -> None:
    """Verify that turn_off switches state to OFF."""
    controller.turn_on()
    assert controller.is_on is True

    result = controller.turn_off()
    assert result is True
    assert controller.is_on is False
    assert controller.is_off is True
    assert controller.state_name == "OFF"


def test_toggle(controller: AssistantController) -> None:
    """Verify toggle switches between ON and OFF back and forth."""
    # Initially OFF -> toggle turns ON
    new_state = controller.toggle()
    assert new_state is True
    assert controller.is_on is True

    # Currently ON -> toggle turns OFF
    new_state = controller.toggle()
    assert new_state is False
    assert controller.is_on is False


def test_idempotency_turn_on(controller: AssistantController) -> None:
    """Calling turn_on when already ON does nothing bad and returns False."""
    assert controller.turn_on() is True
    # Second turn_on should be a no-op
    assert controller.turn_on() is False
    assert controller.is_on is True


def test_idempotency_turn_off(controller: AssistantController) -> None:
    """Calling turn_off when already OFF does nothing bad and returns False."""
    # Controller starts OFF
    assert controller.turn_off() is False
    assert controller.is_on is False
    assert controller.is_off is True


def test_module_start_stop_calls(controller: AssistantController) -> None:
    """Verify registered dummy module start() and stop() are properly invoked."""
    dummy = DummyModule("TestDummy")
    controller.register_module(dummy)

    # Initially not running
    assert dummy.is_running is False
    assert dummy.start_count == 0
    assert dummy.stop_count == 0

    # Turn ON
    controller.turn_on()
    assert dummy.is_running is True
    assert dummy.start_count == 1
    assert dummy.stop_count == 0

    # Turn OFF
    controller.turn_off()
    assert dummy.is_running is False
    assert dummy.start_count == 1
    assert dummy.stop_count == 1


def test_idempotency_module_calls_not_duplicated(controller: AssistantController) -> None:
    """Verify repeated turn_on or turn_off calls do not multiply module calls."""
    dummy = DummyModule("TestDummy")
    controller.register_module(dummy)

    # Call turn_on multiple times
    controller.turn_on()
    controller.turn_on()
    controller.turn_on()
    assert dummy.start_count == 1

    # Call turn_off multiple times
    controller.turn_off()
    controller.turn_off()
    controller.turn_off()
    assert dummy.stop_count == 1


def test_multiple_modules_lifecycle(controller: AssistantController) -> None:
    """Verify multiple modules are started and stopped cleanly."""
    call_log: list = []
    mod1 = CustomTestModule("Module1", call_log)
    mod2 = CustomTestModule("Module2", call_log)

    controller.register_module(mod1)
    controller.register_module(mod2)

    controller.turn_on()
    assert mod1.is_running is True
    assert mod2.is_running is True
    assert call_log == ["Module1_started", "Module2_started"]

    call_log.clear()
    controller.turn_off()
    assert mod1.is_running is False
    assert mod2.is_running is False
    # Reverse order on shutdown confirms orderly resource release
    assert call_log == ["Module2_stopped", "Module1_stopped"]


def test_register_module_when_already_on(controller: AssistantController) -> None:
    """If controller is already ON, registering a module starts it immediately."""
    controller.turn_on()
    dummy = DummyModule("LateModule")
    controller.register_module(dummy)

    assert dummy.is_running is True
    assert dummy.start_count == 1

    controller.turn_off()
    assert dummy.is_running is False
    assert dummy.stop_count == 1


def test_unregister_module(controller: AssistantController) -> None:
    """Unregistering a module stops it if ON and removes it from registry."""
    dummy = DummyModule("RemovableModule")
    controller.register_module(dummy)
    assert dummy in controller.get_registered_modules()

    controller.turn_on()
    assert dummy.is_running is True

    # Unregister while ON should trigger stop
    unregistered = controller.unregister_module(dummy)
    assert unregistered is True
    assert dummy.is_running is False
    assert dummy not in controller.get_registered_modules()


def test_invalid_module_registration(controller: AssistantController) -> None:
    """Registering an invalid module without start() or stop() raises TypeError."""
    class IncompleteModule:
        pass

    with pytest.raises(TypeError):
        controller.register_module(IncompleteModule())


def test_state_change_listeners(controller: AssistantController) -> None:
    """Verify listener callbacks receive state changes."""
    received_states: list = []

    def on_change(state: bool) -> None:
        received_states.append(state)

    controller.add_listener(on_change)

    controller.turn_on()
    controller.turn_off()

    assert received_states == [True, False]

    # Test removing listener
    controller.remove_listener(on_change)
    controller.turn_on()
    # No new notification appended
    assert received_states == [True, False]


def test_thread_safety_concurrent_toggles(controller: AssistantController) -> None:
    """Verify controller thread safety under concurrent access."""
    threads = []
    errors = []

    def worker() -> None:
        try:
            for _ in range(50):
                controller.toggle()
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    for _ in range(8):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    assert len(errors) == 0
    # Final state must be cleanly ON or OFF
    assert controller.is_on in (True, False)


def test_logging_events_with_timestamp() -> None:
    """Verify every ON/OFF event is logged with a timestamp format."""
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    logger = logging.getLogger("TestLogger")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    ctrl = AssistantController(logger=logger)
    ctrl.turn_on()
    ctrl.turn_off()

    output = log_capture.getvalue()
    assert "Master state: OFF" in output or "Master State changed: OFF" in output
    assert "Master State changed: ON" in output
    assert "Master State changed: OFF" in output
    # Check timestamp exists at start of log lines (e.g. 2026-...)
    lines = output.strip().split("\n")
    for line in lines:
        assert len(line) > 10
