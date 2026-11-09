"""
Voice State Machine for HP Assistant (Stage 2.2).
Three explicit states: ACTIVE, PAUSED, SLEEP.
Logs all state transitions (timestamp, from, to, reason) to audit log.
"""

from datetime import datetime
from enum import Enum
import logging
from typing import Callable, List, Optional

from core.permissions import permissions


class VoiceState(str, Enum):
    """Three voice states defined in Stage 2.2."""
    ACTIVE = "Active"
    PAUSED = "Paused"
    SLEEP = "Sleeping"


class VoiceStateMachine:
    """
    Manages explicit voice state transitions and audit logging.
    """

    def __init__(
        self,
        initial_state: VoiceState = VoiceState.SLEEP,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._state: VoiceState = initial_state
        self._logger = logger or logging.getLogger("HP_Assistant.VoiceStateMachine")
        self._listeners: List[Callable[[VoiceState, VoiceState, str], None]] = []

    @property
    def current_state(self) -> VoiceState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state == VoiceState.ACTIVE

    @property
    def is_paused(self) -> bool:
        return self._state == VoiceState.PAUSED

    @property
    def is_sleeping(self) -> bool:
        return self._state == VoiceState.SLEEP

    def add_listener(self, listener: Callable[[VoiceState, VoiceState, str], None]) -> None:
        """Register a callback to be called on state transition."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[VoiceState, VoiceState, str], None]) -> None:
        """Unregister a state transition callback."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def transition(self, to_state: VoiceState, reason: str = "") -> bool:
        """
        Transition to new state, log to audit log with timestamp, and notify listeners.
        """
        from_state = self._state
        if from_state == to_state:
            return False

        self._state = to_state
        self._logger.info(
            "[STATE] VoiceState transition: %s -> %s (Reason: %s)",
            from_state.value,
            to_state.value,
            reason,
        )

        # Log transition in audit log (timestamp, from, to, reason)
        try:
            permissions._write_audit_log(
                action="voice_state_transition",
                level="safe",
                result=f"{from_state.value}->{to_state.value}",
                details=f"from={from_state.value}, to={to_state.value}, reason={reason}",
            )
        except Exception as e:
            self._logger.debug("Failed to write voice state transition to audit log: %s", e)

        # Notify registered listeners
        for listener in list(self._listeners):
            try:
                listener(from_state, to_state, reason)
            except Exception as e:
                self._logger.debug("Error notifying voice state listener: %s", e)

        return True

    def reset(self, reason: str = "reset") -> None:
        """Reset state machine to SLEEP."""
        if self._state != VoiceState.SLEEP:
            self.transition(VoiceState.SLEEP, reason=reason)
