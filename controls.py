"""Configuration and keyboard/mouse button state; no microphone or GUI dependencies."""

import json
import math
import time
from pathlib import Path

# Explicit input allowlist. Mouse buttons never change pointer position.
KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789") | {
    "shift", "ctrl", "alt", "space", "tab", "esc", "enter", "backspace",
    "up", "down", "left", "right", "f1", "f2", "f3", "f4", "f5", "f6", "f7",
    "f9", "f10", "f11", "f12",
}
MOUSE_BUTTONS = {"mouse1": "left", "mouse2": "right"}


def normalize(text):
    return " ".join(text.lower().split())


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("The configuration must be a JSON object.")
    for field, low, high in [("minimum_confidence", 0, 1), ("max_hold_seconds", 1, 300)]:
        value = config.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{field} must be a number from {low} to {high}.")
    if not isinstance(config.get("model_path"), str) or not config["model_path"].strip():
        raise ValueError("model_path must be a folder name.")
    if config.get("microphone") is not None and not isinstance(config["microphone"], str):
        raise ValueError("microphone must be null or a microphone menu label.")
    commands = config.get("commands")
    if not isinstance(commands, dict) or not commands:
        raise ValueError("commands must be a nonempty object.")
    phrases = {}
    for name, command in commands.items():
        if not isinstance(command, dict):
            raise ValueError(f"{name}: expected a command object.")
        action = command.get("action")
        if action not in {"hold", "tap", "release", "stop", "pause"}:
            raise ValueError(f"{name}: action must be hold, tap, release, stop, or pause.")
        aliases = command.get("phrases")
        if not isinstance(aliases, list) or not aliases:
            raise ValueError(f"{name}: phrases must be a nonempty list.")
        for phrase in aliases:
            if not isinstance(phrase, str) or not normalize(phrase) or "[" in phrase or "]" in phrase:
                raise ValueError(f"{name}: phrases must contain ordinary spoken words.")
            phrase = normalize(phrase)
            if phrase in phrases:
                raise ValueError(f"Duplicate phrase: {phrase}")
            phrases[phrase] = (name, command)
        if action in {"hold", "tap"}:
            keys = command.get("keys")
            if not isinstance(keys, list) or not keys or any(
                not isinstance(k, str) or k not in KEYS | MOUSE_BUTTONS.keys() for k in keys
            ):
                raise ValueError(f"{name}: keys must be keyboard keys, mouse1, or mouse2 (F8 is reserved).")
            if len(set(keys)) != len(keys):
                raise ValueError(f"{name}: duplicate key.")
        if action in {"hold", "release"} and (
            not isinstance(command.get("group"), str) or not command["group"].strip()
        ):
            raise ValueError(f"{name}: hold/release requires a group name.")
    return config, phrases


class KeyboardController:
    def __init__(self, backend, max_hold_seconds, clock=time.monotonic):
        self.backend = backend
        self.max_hold_seconds = max_hold_seconds
        self.clock = clock
        self.groups = {}
        self.down = set()
        self.tap_deadlines = {}
        self.hold_deadline = None

    def _press(self, key):
        if key in MOUSE_BUTTONS:
            self.backend.mouseDown(button=MOUSE_BUTTONS[key])
        else:
            self.backend.keyDown(key)

    def _release(self, key):
        if key in MOUSE_BUTTONS:
            self.backend.mouseUp(button=MOUSE_BUTTONS[key])
        else:
            self.backend.keyUp(key)

    def _sync(self):
        wanted = set(self.tap_deadlines)
        for keys in self.groups.values():
            wanted.update(keys)
        for key in sorted(self.down - wanted):
            self._release(key)
            self.down.remove(key)
        for key in sorted(wanted - self.down):
            # Track before sending so cleanup attempts a release even after an error.
            self.down.add(key)
            self._press(key)

    def execute(self, command):
        action = command["action"]
        if action in {"stop", "pause"}:
            self.release_all()
        elif action == "hold":
            self.groups[command["group"]] = set(command["keys"])
            self.hold_deadline = self.clock() + self.max_hold_seconds
            self._sync()
        elif action == "release":
            self.groups.pop(command["group"], None)
            self._sync()
        elif action == "tap":
            for key in command["keys"]:
                self.tap_deadlines[key] = self.clock() + 0.08
            self._sync()

    def tick(self):
        now = self.clock()
        expired = self.hold_deadline is not None and now >= self.hold_deadline
        if expired:
            self.groups.clear()
            self.hold_deadline = None
        self.tap_deadlines = {k: end for k, end in self.tap_deadlines.items() if end > now}
        self._sync()
        return expired

    def release_all(self):
        self.groups.clear()
        self.tap_deadlines.clear()
        self.hold_deadline = None
        errors = []
        for key in sorted(self.down):
            try:
                self._release(key)
                self.down.remove(key)
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError(f"Could not release all keys/buttons: {errors[0]}")
