"""
Unit tests for HP Assistant Voice Module (Stage 2).
Covers:
- CommandRouter mapping for test commands ("what time is it", "hello", "stop listening")
- Stage 1.5 permission confirmation hook via voice ("yes" / "no")
- VoiceModule start/stop resource release (mocked mic)
- Master OFF forces VoiceModule to stop
- Audio listener mic mute flag during TTS
"""

from unittest.mock import MagicMock, patch
import pytest

from core.controller import AssistantController
from core.permissions import permissions
from core.tts import is_speaking, set_speaking
from modules.voice.module import VoiceModule
from modules.voice.router import CommandRouter


@pytest.fixture
def controller() -> AssistantController:
    """Provides a fresh controller instance."""
    return AssistantController()


@pytest.fixture
def router(controller: AssistantController) -> CommandRouter:
    """Provides a CommandRouter instance connected to controller."""
    return CommandRouter(controller=controller)


def test_router_what_time_is_it(router: CommandRouter) -> None:
    """Verify 'what time is it' command is recognized and handled."""
    with patch("modules.voice.router.speak") as mock_speak:
        result = router.handle("what time is it")
        assert result is True
        mock_speak.assert_called_once()
        assert "The time is" in mock_speak.call_args[0][0]


def test_router_hello(router: CommandRouter) -> None:
    """Verify 'hello' greeting is recognized and handled."""
    with patch("modules.voice.router.speak") as mock_speak:
        result = router.handle("hello")
        assert result is True
        mock_speak.assert_called_once()
        assert "Hello!" in mock_speak.call_args[0][0]


def test_router_stop_listening(controller: AssistantController, router: CommandRouter) -> None:
    """Verify 'stop listening' turns the Voice feature OFF through the controller."""
    controller.turn_on()
    controller.turn_on_feature("voice")
    assert controller.is_feature_on("voice") is True

    with patch("modules.voice.router.speak"):
        result = router.handle("stop listening")
        assert result is True
        # Controller voice feature should now be OFF
        assert controller.is_feature_on("voice") is False
        # Master should remain ON
        assert controller.is_on is True


def test_router_permission_confirmation_hook(router: CommandRouter) -> None:
    """Verify voice 'yes' and 'no' hook into active permission confirmation dialogs."""
    with patch.object(permissions, "is_confirmation_active", return_value=True):
        with patch.object(permissions, "voice_confirm") as mock_confirm:
            with patch("modules.voice.router.speak"):
                # Test 'yes'
                result_yes = router.handle("yes please confirm")
                assert result_yes is True
                mock_confirm.assert_called_with(True)

                # Test 'no'
                result_no = router.handle("no cancel it")
                assert result_no is True
                mock_confirm.assert_called_with(False)


def test_voice_module_start_stop_mocked(controller: AssistantController) -> None:
    """Verify VoiceModule starts and stops cleanly, releasing mic resources."""
    voice_module = VoiceModule(controller=controller)

    # Mock audio listener and wake detector so no physical mic is accessed
    voice_module._audio_listener.start = MagicMock(return_value=True)
    voice_module._audio_listener.stop = MagicMock()
    voice_module._wake_detector.initialize = MagicMock(return_value=True)

    assert voice_module.is_running is False

    # Start module
    voice_module.start()
    assert voice_module.is_running is True
    voice_module._audio_listener.start.assert_called_once()

    # Stop module
    voice_module.stop()
    assert voice_module.is_running is False
    voice_module._audio_listener.stop.assert_called_once()


def test_master_off_stops_voice(controller: AssistantController) -> None:
    """Verify Master OFF forcefully stops VoiceModule and releases resources."""
    voice_module = VoiceModule(controller=controller)
    voice_module._audio_listener.start = MagicMock(return_value=True)
    voice_module._audio_listener.stop = MagicMock()
    voice_module._wake_detector.initialize = MagicMock(return_value=True)

    controller.register_module(voice_module, feature="voice")

    controller.turn_on()
    controller.turn_on_feature("voice")
    assert voice_module.is_running is True

    # Master OFF
    controller.turn_off()
    assert voice_module.is_running is False
    assert controller.is_feature_on("voice") is False
    voice_module._audio_listener.stop.assert_called_once()


def test_speaking_mute_flag() -> None:
    """Verify is_speaking() state tracks TTS playback to prevent mic self-triggering."""
    assert is_speaking() is False
    set_speaking(True)
    assert is_speaking() is True
    set_speaking(False)
    assert is_speaking() is False
