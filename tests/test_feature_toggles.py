"""
Unit tests for HP Assistant feature toggles (Voice, Gestures).
Verifies master switch hierarchy, independent feature switches, and module lifecycles.
"""

import logging
import pytest
from core.controller import AssistantController, BaseModule, DummyModule


class FeatureTrackingModule(BaseModule):
    """Test module tracking execution counts."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.is_running = False
        self.start_count = 0
        self.stop_count = 0

    @property
    def name(self) -> str:
        return self._name

    def start(self) -> None:
        self.is_running = True
        self.start_count += 1

    def stop(self) -> None:
        self.is_running = False
        self.stop_count += 1


@pytest.fixture
def controller() -> AssistantController:
    """Fixture providing a fresh controller instance."""
    logger = logging.getLogger("TestFeatureController")
    logger.setLevel(logging.DEBUG)
    return AssistantController(logger=logger)


def test_default_features_state_is_off(controller: AssistantController) -> None:
    """Verify Master and all feature toggles default to OFF."""
    assert controller.is_on is False
    assert controller.is_feature_on("voice") is False
    assert controller.is_feature_on("gestures") is False


def test_cannot_turn_on_feature_when_master_is_off(controller: AssistantController) -> None:
    """Voice and Gestures can ONLY be turned on when Master is ON."""
    # Master is OFF
    assert controller.is_on is False

    result_voice = controller.turn_on_feature("voice")
    assert result_voice is False
    assert controller.is_feature_on("voice") is False

    result_gestures = controller.turn_on_feature("gestures")
    assert result_gestures is False
    assert controller.is_feature_on("gestures") is False


def test_independent_feature_toggling_when_master_is_on(controller: AssistantController) -> None:
    """Voice and Gestures can be turned ON and OFF independently when Master is ON."""
    controller.turn_on()
    assert controller.is_on is True
    assert controller.is_feature_on("voice") is False
    assert controller.is_feature_on("gestures") is False

    # Turn voice ON
    assert controller.turn_on_feature("voice") is True
    assert controller.is_feature_on("voice") is True
    assert controller.is_feature_on("gestures") is False

    # Turn gestures ON
    assert controller.turn_on_feature("gestures") is True
    assert controller.is_feature_on("voice") is True
    assert controller.is_feature_on("gestures") is True

    # Turn voice OFF
    assert controller.turn_off_feature("voice") is True
    assert controller.is_feature_on("voice") is False
    assert controller.is_feature_on("gestures") is True

    # Turn gestures OFF
    assert controller.turn_off_feature("gestures") is True
    assert controller.is_feature_on("voice") is False
    assert controller.is_feature_on("gestures") is False


def test_master_off_forces_both_features_off(controller: AssistantController) -> None:
    """Turning Master OFF forces both Voice and Gestures OFF immediately."""
    controller.turn_on()
    controller.turn_on_feature("voice")
    controller.turn_on_feature("gestures")

    assert controller.is_on is True
    assert controller.is_feature_on("voice") is True
    assert controller.is_feature_on("gestures") is True

    # Master OFF
    controller.turn_off()
    assert controller.is_on is False
    assert controller.is_feature_on("voice") is False
    assert controller.is_feature_on("gestures") is False


def test_feature_module_lifecycle(controller: AssistantController) -> None:
    """Modules registered under features start and stop with their respective feature toggle."""
    core_mod = FeatureTrackingModule("CoreModule")
    voice_mod = FeatureTrackingModule("VoiceModule")
    gesture_mod = FeatureTrackingModule("GestureModule")

    controller.register_module(core_mod, feature=None)
    controller.register_module(voice_mod, feature="voice")
    controller.register_module(gesture_mod, feature="gestures")

    # Initial state
    assert core_mod.is_running is False
    assert voice_mod.is_running is False
    assert gesture_mod.is_running is False

    # Turn Master ON -> only core_mod starts
    controller.turn_on()
    assert core_mod.is_running is True
    assert voice_mod.is_running is False
    assert gesture_mod.is_running is False

    # Turn Voice ON -> voice_mod starts
    controller.turn_on_feature("voice")
    assert voice_mod.is_running is True
    assert gesture_mod.is_running is False

    # Turn Gestures ON -> gesture_mod starts
    controller.turn_on_feature("gestures")
    assert gesture_mod.is_running is True

    # Turn Voice OFF -> voice_mod stops, gestures and core stay running
    controller.turn_off_feature("voice")
    assert voice_mod.is_running is False
    assert gesture_mod.is_running is True
    assert core_mod.is_running is True

    # Turn Master OFF -> forces both features and core off
    controller.turn_off()
    assert core_mod.is_running is False
    assert gesture_mod.is_running is False
    assert voice_mod.is_running is False


def test_feature_idempotency(controller: AssistantController) -> None:
    """Repeated turn_on_feature or turn_off_feature calls are safe no-ops."""
    voice_mod = FeatureTrackingModule("VoiceMod")
    controller.register_module(voice_mod, feature="voice")

    controller.turn_on()
    assert controller.turn_on_feature("voice") is True
    assert voice_mod.start_count == 1

    # Second call should be no-op
    assert controller.turn_on_feature("voice") is False
    assert voice_mod.start_count == 1

    # Turn off
    assert controller.turn_off_feature("voice") is True
    assert voice_mod.stop_count == 1

    # Second turn off should be no-op
    assert controller.turn_off_feature("voice") is False
    assert voice_mod.stop_count == 1


def test_toggle_feature_method(controller: AssistantController) -> None:
    """toggle_feature flips state between ON and OFF."""
    controller.turn_on()

    # OFF -> ON
    res1 = controller.toggle_feature("voice")
    assert res1 is True
    assert controller.is_feature_on("voice") is True

    # ON -> OFF
    res2 = controller.toggle_feature("voice")
    assert res2 is False
    assert controller.is_feature_on("voice") is False
