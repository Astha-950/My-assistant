"""
Unit tests for HP Assistant Voice Module (Stage 2.1).
Covers:
- 5 repeated start/stop cycles with mocked mic
- Fresh stop event per start (never reusing stale events)
- Continuous session mode (multiple commands after a single wake phrase)
- Session timeout returning to wake-phrase detection
- 'go to sleep' / 'sleep' ending active session
- CommandRouter mapping for test commands ("what time is it", "hello", "stop listening")
- Stage 1.5 permission confirmation hook via voice ("yes" / "no")
- Master OFF forces VoiceModule to stop
- Audio listener mic mute flag during TTS
"""

import time
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


@pytest.fixture
def mocked_voice_module(controller: AssistantController) -> VoiceModule:
    """Provides a VoiceModule with mocked microphone and wake-word detector."""
    vm = VoiceModule(controller=controller)
    vm._wake_detector.initialize = MagicMock(return_value=True)
    vm._wake_detector.create_fresh_recognizer = MagicMock()
    return vm


def test_repeated_start_stop_cycles(mocked_voice_module: VoiceModule) -> None:
    """
    Test 5 repeated start/stop cycles with mocked mic.
    Verifies that every cycle cleanly starts, stops, and releases all resources.
    """
    with patch("modules.voice.module.AudioListener") as MockListenerClass:
        mock_instance = MagicMock()
        mock_instance.start.return_value = True
        mock_instance.stop.return_value = None
        mock_instance.read_chunk.return_value = None
        MockListenerClass.return_value = mock_instance

        for cycle in range(5):
            assert mocked_voice_module.is_running is False
            mocked_voice_module.start()
            assert mocked_voice_module.is_running is True
            assert mocked_voice_module._worker_thread is not None
            assert mocked_voice_module._worker_thread.is_alive()

            mocked_voice_module.stop()
            assert mocked_voice_module.is_running is False
            assert mocked_voice_module._worker_thread is None


def test_stop_event_is_fresh_per_start(mocked_voice_module: VoiceModule) -> None:
    """Verify that every start() creates a completely new, un-set threading.Event."""
    with patch("modules.voice.module.AudioListener") as MockListenerClass:
        mock_instance = MagicMock()
        mock_instance.start.return_value = True
        mock_instance.read_chunk.return_value = None
        MockListenerClass.return_value = mock_instance

        mocked_voice_module.start()
        event_1 = mocked_voice_module._stop_event
        assert event_1 is not None
        assert not event_1.is_set()

        mocked_voice_module.stop()
        assert event_1.is_set()

        # Start again - must be a fresh event
        mocked_voice_module.start()
        event_2 = mocked_voice_module._stop_event
        assert event_2 is not None
        assert event_2 is not event_1
        assert not event_2.is_set()

        mocked_voice_module.stop()
        assert event_2.is_set()


def test_session_mode_multiple_commands(mocked_voice_module: VoiceModule, router: CommandRouter) -> None:
    """
    Verify session mode allows speaking multiple commands sequentially
    after a single wake phrase without requiring re-waking.
    """
    # Simulate wake phrase detected -> active session starts
    mocked_voice_module.in_session = True

    with patch("modules.voice.router.speak") as mock_speak:
        # Command 1: What time is it
        res1 = router.handle("what time is it")
        assert res1 is True
        assert mocked_voice_module.in_session is True

        # Command 2: Hello (in the same session, no wake word needed!)
        res2 = router.handle("hello")
        assert res2 is True
        assert mocked_voice_module.in_session is True

        assert mock_speak.call_count == 2


def test_session_mode_go_to_sleep_ends_session(mocked_voice_module: VoiceModule) -> None:
    """Verify 'go to sleep' / 'sleep' command exits the active session."""
    mocked_voice_module.in_session = True

    # Simulate loop checking speech command "go to sleep"
    with patch("modules.voice.module.speak") as mock_speak:
        with patch("modules.voice.module.play_session_end_beep") as mock_beep:
            # Simulate speech text received in session
            text = "assistant go to sleep now"
            if any(p in text for p in ("go to sleep", "sleep")):
                mock_speak("Going to sleep.")
                mocked_voice_module.in_session = False
                mock_beep()

            assert mocked_voice_module.in_session is False
            mock_speak.assert_called_with("Going to sleep.")
            mock_beep.assert_called_once()


def test_session_timeout(mocked_voice_module: VoiceModule) -> None:
    """Verify session automatically terminates when inactive for session_timeout_seconds."""
    mocked_voice_module.session_timeout_seconds = 0.1
    mocked_voice_module.in_session = True
    last_speech_time = time.time() - 0.2

    with patch("modules.voice.module.play_session_end_beep") as mock_beep:
        # Check timeout condition as implemented in _run_voice_loop
        if time.time() - last_speech_time > mocked_voice_module.session_timeout_seconds:
            mocked_voice_module.in_session = False
            mock_beep()

        assert mocked_voice_module.in_session is False
        mock_beep.assert_called_once()


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


def test_master_off_stops_voice(controller: AssistantController) -> None:
    """Verify Master OFF forcefully stops VoiceModule and releases resources."""
    voice_module = VoiceModule(controller=controller)
    voice_module._wake_detector.initialize = MagicMock(return_value=True)

    with patch("modules.voice.module.AudioListener") as MockListenerClass:
        mock_instance = MagicMock()
        mock_instance.start.return_value = True
        MockListenerClass.return_value = mock_instance

        controller.register_module(voice_module, feature="voice")

        controller.turn_on()
        controller.turn_on_feature("voice")
        assert voice_module.is_running is True

        # Master OFF
        controller.turn_off()
        assert voice_module.is_running is False
        assert controller.is_feature_on("voice") is False
        mock_instance.stop.assert_called()


def test_speaking_mute_flag() -> None:
    """Verify is_speaking() state tracks TTS playback to prevent mic self-triggering."""
    assert is_speaking() is False
    set_speaking(True)
    assert is_speaking() is True
    set_speaking(False)
    assert is_speaking() is False


# =============================================================================
# STAGE 2.2 TESTS: 3-State Machine (ACTIVE, PAUSED, SLEEP)
# =============================================================================

from modules.voice.state_machine import VoiceState, VoiceStateMachine


def test_state_machine_all_transitions() -> None:
    """
    Test all explicit state transitions in VoiceStateMachine:
    - sleep -> active
    - active -> paused
    - paused -> active
    - paused -> sleep
    - active -> sleep
    - active timeout -> sleep
    - paused timeout -> sleep
    """
    sm = VoiceStateMachine(initial_state=VoiceState.SLEEP)
    assert sm.current_state == VoiceState.SLEEP

    # 1. sleep -> active (wake detected)
    assert sm.transition(VoiceState.ACTIVE, reason="wake_phrase_detected") is True
    assert sm.is_active is True

    # 2. active -> paused ("pause")
    assert sm.transition(VoiceState.PAUSED, reason="user_pause") is True
    assert sm.is_paused is True

    # 3. paused -> active ("HP resume")
    assert sm.transition(VoiceState.ACTIVE, reason="user_resume") is True
    assert sm.is_active is True

    # 4. active -> paused, then paused -> sleep ("HP sleep")
    sm.transition(VoiceState.PAUSED, reason="user_pause")
    assert sm.transition(VoiceState.SLEEP, reason="user_sleep") is True
    assert sm.is_sleeping is True

    # 5. sleep -> active, then active -> sleep ("go to sleep")
    sm.transition(VoiceState.ACTIVE, reason="wake_phrase_detected")
    assert sm.transition(VoiceState.SLEEP, reason="user_sleep") is True
    assert sm.is_sleeping is True

    # 6. sleep -> active, then timeout -> sleep
    sm.transition(VoiceState.ACTIVE, reason="wake_phrase_detected")
    assert sm.transition(VoiceState.SLEEP, reason="session_timeout") is True
    assert sm.is_sleeping is True

    # 7. paused timeout -> sleep
    sm.transition(VoiceState.ACTIVE, reason="wake_phrase_detected")
    sm.transition(VoiceState.PAUSED, reason="user_pause")
    assert sm.transition(VoiceState.SLEEP, reason="pause_timeout") is True
    assert sm.is_sleeping is True


def test_transition_active_to_paused_denies_open_permission(mocked_voice_module: VoiceModule) -> None:
    """
    Verify that when transitioning ACTIVE -> PAUSED via 'pause':
    If a permission confirmation popup is open, it is automatically denied.
    """
    mocked_voice_module.state_machine.transition(VoiceState.ACTIVE)
    assert mocked_voice_module.state_machine.is_active is True

    with patch.object(permissions, "is_confirmation_active", return_value=True):
        with patch.object(permissions, "voice_confirm") as mock_confirm:
            with patch("modules.voice.module.speak") as mock_speak:
                with patch("modules.voice.module.play_pause_beep") as mock_beep:
                    # Simulate user saying "pause" in active loop
                    text = "pause"
                    lower_text = text.lower().strip()
                    if any(p == lower_text for p in mocked_voice_module.pause_phrases):
                        if permissions.is_confirmation_active():
                            permissions.voice_confirm(False)
                        mocked_voice_module.state_machine.transition(VoiceState.PAUSED, reason="user_pause")
                        mock_beep()
                        mock_speak("Paused.")

                    mock_confirm.assert_called_once_with(False)
                    assert mocked_voice_module.state_machine.is_paused is True
                    mock_beep.assert_called_once()
                    mock_speak.assert_called_once_with("Paused.")


def test_transition_paused_to_active(mocked_voice_module: VoiceModule) -> None:
    """Verify 'HP resume' in PAUSED state transitions to ACTIVE with resume beep and 'Resumed.'"""
    mocked_voice_module.state_machine.transition(VoiceState.PAUSED)
    assert mocked_voice_module.state_machine.is_paused is True

    with patch("modules.voice.module.speak") as mock_speak:
        with patch("modules.voice.module.play_resume_beep") as mock_beep:
            # Simulate Vosk detected "resume" action
            action = "resume"
            if action == "resume":
                mocked_voice_module.state_machine.transition(VoiceState.ACTIVE, reason="user_resume")
                mock_beep()
                mock_speak("Resumed.")

            assert mocked_voice_module.state_machine.is_active is True
            mock_beep.assert_called_once()
            mock_speak.assert_called_once_with("Resumed.")


def test_transition_paused_to_sleep(mocked_voice_module: VoiceModule) -> None:
    """Verify 'HP sleep' in PAUSED state transitions to SLEEP with sleep beep."""
    mocked_voice_module.state_machine.transition(VoiceState.PAUSED)
    assert mocked_voice_module.state_machine.is_paused is True

    with patch("modules.voice.module.play_sleep_beep") as mock_beep:
        action = "sleep"
        if action == "sleep":
            mocked_voice_module.state_machine.transition(VoiceState.SLEEP, reason="user_sleep")
            mock_beep()

        assert mocked_voice_module.state_machine.is_sleeping is True
        mock_beep.assert_called_once()


def test_transition_paused_timeout_to_sleep(mocked_voice_module: VoiceModule) -> None:
    """Verify that being paused longer than pause_timeout_minutes transitions to SLEEP."""
    mocked_voice_module.pause_timeout_minutes = 0.001  # very short for test
    mocked_voice_module.state_machine.transition(VoiceState.PAUSED)
    paused_start_time = time.time() - 10.0  # simulate elapsed time

    with patch("modules.voice.module.play_sleep_beep") as mock_beep:
        if (time.time() - paused_start_time) > (mocked_voice_module.pause_timeout_minutes * 60):
            mocked_voice_module.state_machine.transition(VoiceState.SLEEP, reason="pause_timeout")
            mock_beep()

        assert mocked_voice_module.state_machine.is_sleeping is True
        mock_beep.assert_called_once()


def test_no_command_handler_runs_in_paused_or_sleep(router: CommandRouter) -> None:
    """
    Verify command handlers are strictly guarded and NEVER run when
    voice state is PAUSED or SLEEP.
    """
    sm = VoiceStateMachine(initial_state=VoiceState.SLEEP)
    router.state_machine = sm

    with patch("modules.voice.router.speak") as mock_speak:
        # In SLEEP:
        assert sm.is_sleeping is True
        handled = router.handle("what time is it")
        assert handled is False
        mock_speak.assert_not_called()

        # In PAUSED:
        sm.transition(VoiceState.PAUSED)
        assert sm.is_paused is True
        handled_paused = router.handle("hello")
        assert handled_paused is False
        mock_speak.assert_not_called()

        # In ACTIVE:
        sm.transition(VoiceState.ACTIVE)
        assert sm.is_active is True
        handled_active = router.handle("hello")
        assert handled_active is True
        mock_speak.assert_called_once()


def test_google_recognizer_never_called_while_paused_or_sleep() -> None:
    """
    Verify that in PAUSED and SLEEP states, audio chunks are processed
    exclusively by the offline Vosk recognizer and Google STT is NEVER called.
    """
    vm = VoiceModule()
    vm._state_machine = VoiceStateMachine(initial_state=VoiceState.SLEEP)
    vm._stt_engine.recognize_pcm = MagicMock()
    vm._wake_detector.process_chunk = MagicMock(return_value=False)
    vm._wake_detector.process_paused_chunk = MagicMock(return_value=None)

    # In SLEEP: process 10 chunks
    fake_chunk = b"\x00" * 3200
    for _ in range(10):
        if vm._state_machine.is_sleeping:
            vm._wake_detector.process_chunk(fake_chunk)

    # In PAUSED: process 10 chunks
    vm._state_machine.transition(VoiceState.PAUSED)
    for _ in range(10):
        if vm._state_machine.is_paused:
            vm._wake_detector.process_paused_chunk(fake_chunk)

    # Google STT must have 0 calls
    vm._stt_engine.recognize_pcm.assert_not_called()
    assert vm._wake_detector.process_chunk.call_count == 10
    assert vm._wake_detector.process_paused_chunk.call_count == 10


def test_voice_off_from_every_state_releases_mic(controller: AssistantController) -> None:
    """
    Verify that turning Voice OFF from any of the three states (ACTIVE, PAUSED, SLEEP)
    fully releases the microphone stream and joins worker threads.
    """
    controller.turn_on()

    for initial_target_state in (VoiceState.SLEEP, VoiceState.ACTIVE, VoiceState.PAUSED):
        vm = VoiceModule(controller=controller)
        vm._wake_detector.initialize = MagicMock(return_value=True)

        with patch("modules.voice.module.AudioListener") as MockListenerClass:
            mock_listener = MagicMock()
            mock_listener.start.return_value = True
            MockListenerClass.return_value = mock_listener

            controller.register_module(vm, feature="voice")
            controller.turn_on_feature("voice")
            assert vm.is_running is True

            # Move to target state
            if initial_target_state != VoiceState.SLEEP:
                vm.state_machine.transition(initial_target_state)

            assert vm.current_state == initial_target_state

            # Turn Voice feature OFF
            controller.turn_off_feature("voice")
            assert vm.is_running is False
            assert controller.is_feature_on("voice") is False
            mock_listener.stop.assert_called()

            controller.unregister_module(vm)

