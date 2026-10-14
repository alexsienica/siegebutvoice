import json
import tempfile
import unittest
from pathlib import Path

from controls import KeyboardController, load_config


class FakeKeyboard:
    def __init__(self):
        self.down = set()
        self.events = []

    def keyDown(self, key):
        self.down.add(key)
        self.events.append(("down", key))

    def keyUp(self, key):
        self.down.discard(key)
        self.events.append(("up", key))

    def mouseDown(self, *, button):
        key = {"left": "mouse1", "right": "mouse2"}[button]
        self.down.add(key)
        self.events.append(("mouse down", button))

    def mouseUp(self, *, button):
        key = {"left": "mouse1", "right": "mouse2"}[button]
        self.down.discard(key)
        self.events.append(("mouse up", button))


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.config, self.phrases = load_config(Path(__file__).resolve().parents[1] / "config.json")
        self.keyboard = FakeKeyboard()
        self.now = 0
        self.controller = KeyboardController(self.keyboard, 30, lambda: self.now)

    def command(self, phrase):
        self.controller.execute(self.phrases[phrase][1])

    def test_opposite_direction_releases_previous_key(self):
        self.command("walk")
        self.command("back")
        self.assertEqual(self.keyboard.down, {"s"})
        self.assertLess(self.keyboard.events.index(("up", "w")), self.keyboard.events.index(("down", "s")))

    def test_diagonal_and_sprint_to_walk(self):
        self.command("run")
        self.command("left")
        self.assertEqual(self.keyboard.down, {"w", "shift", "a"})
        self.command("walk")
        self.assertEqual(self.keyboard.down, {"w", "a"})
        self.command("stop")
        self.assertFalse(self.keyboard.down)

    def test_silence_timeout_releases_movement(self):
        self.command("walk")
        self.now = 31
        self.assertTrue(self.controller.tick())
        self.assertFalse(self.keyboard.down)

    def test_tap_releases_without_releasing_movement(self):
        self.command("walk")
        self.command("reload")
        self.assertEqual(self.keyboard.down, {"w", "r"})
        self.now = 0.1
        self.controller.tick()
        self.assertEqual(self.keyboard.down, {"w"})

    def test_shared_key_stays_down_until_last_group_releases(self):
        for group in ("one", "two"):
            self.controller.execute({"action": "hold", "keys": ["w"], "group": group})
        self.controller.execute({"action": "release", "group": "one"})
        self.assertEqual(self.keyboard.down, {"w"})
        self.controller.execute({"action": "release", "group": "two"})
        self.assertFalse(self.keyboard.down)

    def test_pause_releases_everything(self):
        self.command("run")
        self.command("reload")
        self.command("pause controls")
        self.assertFalse(self.keyboard.down)
        self.assertFalse(self.controller.tap_deadlines)

    def test_cleanup_attempts_other_keys_when_one_release_fails(self):
        self.command("run")
        original = self.keyboard.keyUp

        def fail_shift(key):
            if key == "shift":
                raise RuntimeError("test failure")
            original(key)

        self.keyboard.keyUp = fail_shift
        with self.assertRaises(RuntimeError):
            self.controller.release_all()
        self.assertNotIn("w", self.keyboard.down)
        self.assertEqual(self.controller.down, {"shift"})
        self.keyboard.keyUp = original
        self.controller.release_all()
        self.assertFalse(self.keyboard.down)

    def check_invalid(self, change):
        change(self.config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(self.config), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_unknown_mouse_bindings_are_rejected(self):
        self.check_invalid(lambda c: c["commands"]["reload"].update(keys=["leftmouse"]))

    def test_shoot_and_aim_hold_both_buttons_independently(self):
        self.command("shoot")
        self.command("aim")
        self.assertEqual(self.keyboard.down, {"mouse1", "mouse2"})
        self.assertEqual(self.keyboard.events, [("mouse down", "left"), ("mouse down", "right")])
        self.command("stop shooting")
        self.assertEqual(self.keyboard.down, {"mouse2"})
        self.command("stop aiming")
        self.assertFalse(self.keyboard.down)

    def test_repeated_shoot_does_not_press_again(self):
        self.command("shoot")
        self.command("shoot")
        self.assertEqual(self.keyboard.events, [("mouse down", "left")])

    def test_shoot_releases_at_configured_duration_and_keeps_other_inputs(self):
        self.command("walk")
        self.command("aim")
        self.command("shoot")
        duration = self.config["commands"]["shoot"]["duration_seconds"]
        self.now = duration - 0.001
        self.controller.tick()
        self.assertEqual(self.keyboard.down, {"w", "mouse1", "mouse2"})
        self.now = duration
        self.controller.tick()
        self.assertEqual(self.keyboard.down, {"w", "mouse2"})

    def test_other_commands_do_not_extend_shoot_timer(self):
        self.command("shoot")
        duration = self.config["commands"]["shoot"]["duration_seconds"]
        self.now = duration / 2
        self.command("walk")
        self.command("aim")
        self.now = duration
        self.controller.tick()
        self.assertEqual(self.keyboard.down, {"w", "mouse2"})

    def test_repeating_shoot_restarts_its_timer(self):
        self.command("shoot")
        duration = self.config["commands"]["shoot"]["duration_seconds"]
        self.now = duration / 2
        self.command("shoot")
        self.now = duration
        self.controller.tick()
        self.assertIn("mouse1", self.keyboard.down)
        self.now = duration * 1.5
        self.controller.tick()
        self.assertNotIn("mouse1", self.keyboard.down)

    def test_shoot_duration_can_be_changed(self):
        command = dict(self.phrases["shoot"][1], duration_seconds=2.5)
        self.controller.execute(command)
        self.now = 2.49
        self.controller.tick()
        self.assertIn("mouse1", self.keyboard.down)
        self.now = 2.5
        self.controller.tick()
        self.assertFalse(self.keyboard.down)

    def test_stop_clears_timed_holds(self):
        self.command("shoot")
        self.command("stop")
        self.assertFalse(self.controller.group_deadlines)
        self.now = 2
        self.command("walk")
        self.controller.tick()
        self.assertEqual(self.keyboard.down, {"w"})

    def test_untimed_replacement_removes_previous_timer(self):
        self.command("shoot")
        self.controller.execute({"action": "hold", "keys": ["w"], "group": "shooting"})
        self.now = 2
        self.controller.tick()
        self.assertEqual(self.keyboard.down, {"w"})

    def test_invalid_durations_are_rejected(self):
        for value in (0, -1, 301, True, "1", float("nan"), float("inf")):
            with self.subTest(value=value):
                self.check_invalid(lambda c: c["commands"]["shoot"].update(duration_seconds=value))

    def test_duration_on_non_hold_is_rejected(self):
        self.check_invalid(lambda c: c["commands"]["reload"].update(duration_seconds=1))

    def test_stop_and_pause_release_mouse_and_keyboard(self):
        for phrase in ("stop", "pause controls"):
            with self.subTest(phrase=phrase):
                self.command("shoot")
                self.command("aim")
                self.command("walk")
                self.command(phrase)
                self.assertFalse(self.keyboard.down)

    def test_timeout_releases_both_mouse_buttons(self):
        self.command("shoot")
        self.command("aim")
        self.now = 31
        self.assertTrue(self.controller.tick())
        self.assertFalse(self.keyboard.down)

    def test_mouse_tap_releases_after_delay(self):
        self.controller.execute({"action": "tap", "keys": ["mouse1"]})
        self.assertEqual(self.keyboard.down, {"mouse1"})
        self.now = 0.1
        self.controller.tick()
        self.assertFalse(self.keyboard.down)

    def test_mouse_release_failure_does_not_prevent_other_releases(self):
        self.command("shoot")
        self.command("aim")
        self.command("walk")
        original = self.keyboard.mouseUp

        def fail_left(*, button):
            if button == "left":
                raise RuntimeError("test failure")
            original(button=button)

        self.keyboard.mouseUp = fail_left
        with self.assertRaises(RuntimeError):
            self.controller.release_all()
        self.assertEqual(self.keyboard.down, {"mouse1"})
        self.keyboard.mouseUp = original
        self.controller.release_all()
        self.assertFalse(self.keyboard.down)

    def test_f8_is_reserved(self):
        self.check_invalid(lambda c: c["commands"]["reload"].update(keys=["f8"]))

    def test_duplicate_aliases_are_rejected(self):
        self.check_invalid(lambda c: c["commands"]["reload"].update(phrases=["  WALK "]))

    def test_invalid_confidence_is_rejected(self):
        self.check_invalid(lambda c: c.update(minimum_confidence=2))


if __name__ == "__main__":
    unittest.main()
