"""
Master controller for HP Assistant.
Maintains application state (ON/OFF) and manages registered module lifecycles.
"""

from abc import ABC, abstractmethod
import logging
import threading
from typing import Any, Callable, List, Optional


class BaseModule(ABC):
    """
    Abstract base class for all HP Assistant modules.
    Modules added in later stages (voice, camera, gestures) must inherit
    from this class and implement start() and stop().
    """

    @property
    def name(self) -> str:
        """Module display name."""
        return getattr(self, "_name", self.__class__.__name__)

    @abstractmethod
    def start(self) -> None:
        """Start module operations and allocate required resources."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop module operations and safely release all resources."""
        pass


class DummyModule(BaseModule):
    """
    A test module to demonstrate and verify start/stop module lifecycle.
    """

    def __init__(self, name: str = "DummyModule") -> None:
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


class AssistantController:
    """
    Thread-safe, idempotent master controller for HP Assistant.
    Default state is OFF every time the application starts.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._is_on: bool = False  # Always OFF by default
        self._lock: threading.RLock = threading.RLock()
        self._modules: List[Any] = []
        self._listeners: List[Callable[[bool], None]] = []
        self._logger = logger or logging.getLogger("HP_Assistant.Controller")
        self._logger.info("[EVENT] Controller initialized. Master state: OFF")

    @property
    def is_on(self) -> bool:
        """Returns True if the assistant is ON, False otherwise."""
        with self._lock:
            return self._is_on

    @property
    def is_off(self) -> bool:
        """Returns True if the assistant is OFF, False otherwise."""
        with self._lock:
            return not self._is_on

    @property
    def state_name(self) -> str:
        """Returns string representation of current state: 'ON' or 'OFF'."""
        with self._lock:
            return "ON" if self._is_on else "OFF"

    def register_module(self, module: Any) -> None:
        """
        Register a module that implements start() and stop().
        If the controller is currently ON, start() is called immediately.
        """
        if not hasattr(module, "start") or not callable(getattr(module, "start")):
            raise TypeError(f"Module '{module}' must implement callable start() method")
        if not hasattr(module, "stop") or not callable(getattr(module, "stop")):
            raise TypeError(f"Module '{module}' must implement callable stop() method")

        with self._lock:
            if module not in self._modules:
                self._modules.append(module)
                mod_name = getattr(module, "name", module.__class__.__name__)
                self._logger.info("Registered module: %s", mod_name)
                # If currently ON, start newly registered module
                if self._is_on:
                    try:
                        module.start()
                    except Exception as e:
                        self._logger.error("Error starting newly registered module %s: %s", mod_name, e, exc_info=True)

    def unregister_module(self, module: Any) -> bool:
        """
        Unregister a module. If the controller is ON, the module is stopped first.
        """
        with self._lock:
            if module in self._modules:
                mod_name = getattr(module, "name", module.__class__.__name__)
                if self._is_on:
                    try:
                        module.stop()
                    except Exception as e:
                        self._logger.error("Error stopping module %s during unregister: %s", mod_name, e)
                self._modules.remove(module)
                self._logger.info("Unregistered module: %s", mod_name)
                return True
            return False

    def get_registered_modules(self) -> List[Any]:
        """Returns a copy of registered modules."""
        with self._lock:
            return list(self._modules)

    def add_listener(self, callback: Callable[[bool], None]) -> None:
        """Register a callback for state changes. Receives bool (True for ON, False for OFF)."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[bool], None]) -> None:
        """Remove a previously registered state change callback."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify_listeners(self, state: bool) -> None:
        """Notify all listeners of a state change outside critical lock section where possible."""
        listeners_snapshot = []
        with self._lock:
            listeners_snapshot = list(self._listeners)

        for listener in listeners_snapshot:
            try:
                listener(state)
            except Exception as e:
                self._logger.error("Error in state change listener: %s", e, exc_info=True)

    def turn_on(self) -> bool:
        """
        Turn the assistant ON. Calls start() on all registered modules.
        Thread-safe and idempotent (calling turn_on when already ON is a no-op).
        Returns True if state changed from OFF to ON, False if already ON.
        """
        with self._lock:
            if self._is_on:
                self._logger.info("[IDEMPOTENT] Controller is already ON. Ignored.")
                return False

            self._is_on = True
            self._logger.info("[EVENT] Master State changed: ON")

            for module in self._modules:
                mod_name = getattr(module, "name", module.__class__.__name__)
                try:
                    self._logger.debug("Starting module: %s", mod_name)
                    module.start()
                except Exception as e:
                    self._logger.error("Failed to start module %s: %s", mod_name, e, exc_info=True)

        self._notify_listeners(True)
        return True

    def turn_off(self) -> bool:
        """
        Turn the assistant OFF. Calls stop() on all registered modules
        and confirms every resource is released.
        Thread-safe and idempotent (calling turn_off when already OFF is a no-op).
        Returns True if state changed from ON to OFF, False if already OFF.
        """
        with self._lock:
            if not self._is_on:
                self._logger.info("[IDEMPOTENT] Controller is already OFF. Ignored.")
                return False

            all_released = True
            # Stop modules in reverse order of registration
            for module in reversed(self._modules):
                mod_name = getattr(module, "name", module.__class__.__name__)
                try:
                    self._logger.debug("Stopping module: %s", mod_name)
                    module.stop()
                    # Verify resource release if supported by module
                    if getattr(module, "is_running", False):
                        all_released = False
                        self._logger.warning("Module %s reports still running after stop()", mod_name)
                except Exception as e:
                    all_released = False
                    self._logger.error("Error stopping module %s: %s", mod_name, e, exc_info=True)

            self._is_on = False
            self._logger.info(
                "[EVENT] Master State changed: OFF | All module resources released: %s",
                all_released,
            )

        self._notify_listeners(False)
        return True

    def toggle(self) -> bool:
        """
        Toggle master state between ON and OFF.
        Thread-safe. Returns the new state (True = ON, False = OFF).
        """
        with self._lock:
            if self._is_on:
                self.turn_off()
                return False
            else:
                self.turn_on()
                return True
