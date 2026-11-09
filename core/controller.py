"""
Master controller for HP Assistant.
Maintains application state (ON/OFF), manages per-feature toggles (voice, gestures),
and manages registered module lifecycles.
"""

from abc import ABC, abstractmethod
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple


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
    Manages master toggle and sub-feature toggles (voice, gestures).
    """

    SUPPORTED_FEATURES = ("voice", "gestures")

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._is_on: bool = False  # Master switch defaults to OFF
        self._lock: threading.RLock = threading.RLock()
        # Per-feature switches default to OFF on every app start
        self._features: Dict[str, bool] = {feat: False for feat in self.SUPPORTED_FEATURES}
        # List of (module_instance, feature_name_or_None)
        self._modules: List[Tuple[Any, Optional[str]]] = []
        self._listeners: List[Callable[..., None]] = []
        self._logger = logger or logging.getLogger("HP_Assistant.Controller")
        self._logger.info("[EVENT] Controller initialized. Master state: OFF | Features: %s", self._features)

    @property
    def is_on(self) -> bool:
        """Returns True if the master assistant state is ON, False otherwise."""
        with self._lock:
            return self._is_on

    @property
    def is_off(self) -> bool:
        """Returns True if the master assistant state is OFF, False otherwise."""
        with self._lock:
            return not self._is_on

    @property
    def state_name(self) -> str:
        """Returns string representation of current state: 'ON' or 'OFF'."""
        with self._lock:
            return "ON" if self._is_on else "OFF"

    def is_feature_on(self, feature_name: str) -> bool:
        """
        Returns True if the feature is ON.
        Voice and gestures can ONLY be ON when master is ON.
        """
        feat = feature_name.lower()
        with self._lock:
            return self._is_on and self._features.get(feat, False)

    def get_feature_states(self) -> Dict[str, bool]:
        """Returns a copy of all feature states."""
        with self._lock:
            return {
                feat: (self._is_on and self._features.get(feat, False))
                for feat in self._features
            }

    def register_module(self, module: Any, feature: Optional[str] = None) -> None:
        """
        Register a module that implements start() and stop().
        Optional feature specifies feature grouping ('voice', 'gestures', or None for core).
        If the feature/master is currently active, start() is called immediately.
        """
        if not hasattr(module, "start") or not callable(getattr(module, "start")):
            raise TypeError(f"Module '{module}' must implement callable start() method")
        if not hasattr(module, "stop") or not callable(getattr(module, "stop")):
            raise TypeError(f"Module '{module}' must implement callable stop() method")

        feat = feature.lower() if feature is not None else None
        mod_name = getattr(module, "name", module.__class__.__name__)

        with self._lock:
            # Check if module already registered
            for existing_mod, _ in self._modules:
                if existing_mod is module:
                    return

            if feat is not None and feat not in self._features:
                self._features[feat] = False

            self._modules.append((module, feat))
            self._logger.info("Registered module: %s (feature: %s)", mod_name, feat or "core")

            # If the relevant feature or master is already ON, start immediately
            should_start = False
            if feat is None:
                should_start = self._is_on
            else:
                should_start = self.is_feature_on(feat)

            if should_start:
                try:
                    module.start()
                except Exception as e:
                    self._logger.error("Error starting newly registered module %s: %s", mod_name, e, exc_info=True)

    def unregister_module(self, module: Any) -> bool:
        """
        Unregister a module. If currently active, the module is stopped first.
        """
        with self._lock:
            for item in list(self._modules):
                existing_mod, feat = item
                if existing_mod is module:
                    mod_name = getattr(module, "name", module.__class__.__name__)
                    is_active = self._is_on if feat is None else self.is_feature_on(feat)
                    if is_active:
                        try:
                            module.stop()
                        except Exception as e:
                            self._logger.error("Error stopping module %s during unregister: %s", mod_name, e)
                    self._modules.remove(item)
                    self._logger.info("Unregistered module: %s", mod_name)
                    return True
            return False

    def get_registered_modules(self, feature: Optional[str] = None) -> List[Any]:
        """Returns registered modules, optionally filtered by feature."""
        with self._lock:
            if feature is None:
                return [mod for mod, _ in self._modules]
            feat = feature.lower()
            return [mod for mod, mod_feat in self._modules if mod_feat == feat]

    def add_listener(self, callback: Callable[..., None]) -> None:
        """Register a callback for state changes."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[..., None]) -> None:
        """Remove a previously registered state change callback."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify_listeners(self, state: bool) -> None:
        """Notify all listeners of a state change."""
        listeners_snapshot = []
        with self._lock:
            listeners_snapshot = list(self._listeners)

        for listener in listeners_snapshot:
            try:
                # Support single-argument listeners (backward compatible)
                listener(state)
            except Exception as e:
                self._logger.error("Error in state change listener: %s", e, exc_info=True)

    def turn_on(self) -> bool:
        """
        Turn master state ON. Starts general/core modules.
        Sub-features (voice, gestures) remain in their configured state (OFF by default)
        and can be toggled independently.
        Thread-safe and idempotent.
        """
        with self._lock:
            if self._is_on:
                self._logger.info("[IDEMPOTENT] Controller is already ON. Ignored.")
                return False

            self._is_on = True
            self._logger.info("[EVENT] Master State changed: ON")

            # Start general (non-feature-specific) modules
            for module, feat in self._modules:
                if feat is None:
                    mod_name = getattr(module, "name", module.__class__.__name__)
                    try:
                        self._logger.debug("Starting core module: %s", mod_name)
                        module.start()
                    except Exception as e:
                        self._logger.error("Failed to start module %s: %s", mod_name, e, exc_info=True)

        self._notify_listeners(True)
        return True

    def turn_off(self) -> bool:
        """
        Turn master state OFF.
        Master OFF forces both voice and gestures OFF and releases all resources.
        Thread-safe and idempotent.
        """
        with self._lock:
            if not self._is_on:
                self._logger.info("[IDEMPOTENT] Controller is already OFF. Ignored.")
                return False

            all_released = True

            # 1. Force all feature modules OFF and mark features as OFF
            for feat in list(self._features.keys()):
                if self._features[feat]:
                    self._logger.info("[EVENT] Master OFF forcing feature '%s' OFF", feat)
                    for module, mod_feat in reversed(self._modules):
                        if mod_feat == feat:
                            mod_name = getattr(module, "name", module.__class__.__name__)
                            try:
                                self._logger.debug("Stopping feature module %s (%s)", mod_name, feat)
                                module.stop()
                                if getattr(module, "is_running", False):
                                    all_released = False
                                    self._logger.warning("Module %s reports still running after stop()", mod_name)
                            except Exception as e:
                                all_released = False
                                self._logger.error("Error stopping module %s: %s", mod_name, e, exc_info=True)
                    self._features[feat] = False

            # 2. Stop core modules in reverse order
            for module, mod_feat in reversed(self._modules):
                if mod_feat is None:
                    mod_name = getattr(module, "name", module.__class__.__name__)
                    try:
                        self._logger.debug("Stopping core module: %s", mod_name)
                        module.stop()
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
        """
        with self._lock:
            if self._is_on:
                self.turn_off()
                return False
            else:
                self.turn_on()
                return True

    def turn_on_feature(self, feature_name: str) -> bool:
        """
        Turn a specific feature ON (e.g. 'voice' or 'gestures').
        Voice and gestures can only run when master is ON.
        Thread-safe and idempotent.
        """
        feat = feature_name.lower()
        with self._lock:
            if not self._is_on:
                self._logger.warning("Cannot turn on feature '%s': Master is OFF", feat)
                return False

            if self._features.get(feat, False):
                self._logger.info("[IDEMPOTENT] Feature '%s' is already ON. Ignored.", feat)
                return False

            self._features[feat] = True
            self._logger.info("[EVENT] Feature State changed: %s = ON", feat)

            for module, mod_feat in self._modules:
                if mod_feat == feat:
                    mod_name = getattr(module, "name", module.__class__.__name__)
                    try:
                        self._logger.debug("Starting %s module: %s", feat, mod_name)
                        module.start()
                    except Exception as e:
                        self._logger.error("Failed to start %s module %s: %s", feat, mod_name, e, exc_info=True)

        self._notify_listeners(self._is_on)
        return True

    def turn_off_feature(self, feature_name: str) -> bool:
        """
        Turn a specific feature OFF (e.g. 'voice' or 'gestures').
        Stops all modules associated with the feature and confirms release.
        Thread-safe and idempotent.
        """
        feat = feature_name.lower()
        with self._lock:
            if not self._features.get(feat, False):
                self._logger.info("[IDEMPOTENT] Feature '%s' is already OFF. Ignored.", feat)
                return False

            all_released = True
            for module, mod_feat in reversed(self._modules):
                if mod_feat == feat:
                    mod_name = getattr(module, "name", module.__class__.__name__)
                    try:
                        self._logger.debug("Stopping %s module: %s", feat, mod_name)
                        module.stop()
                        if getattr(module, "is_running", False):
                            all_released = False
                            self._logger.warning("Module %s reports still running after stop()", mod_name)
                    except Exception as e:
                        all_released = False
                        self._logger.error("Error stopping %s module %s: %s", feat, mod_name, e, exc_info=True)

            self._features[feat] = False
            self._logger.info(
                "[EVENT] Feature State changed: %s = OFF | Released: %s",
                feat,
                all_released,
            )

        self._notify_listeners(self._is_on)
        return True

    def toggle_feature(self, feature_name: str) -> bool:
        """
        Toggle a specific feature ON/OFF.
        """
        feat = feature_name.lower()
        with self._lock:
            if self.is_feature_on(feat):
                self.turn_off_feature(feat)
                return False
            else:
                return self.turn_on_feature(feat)
