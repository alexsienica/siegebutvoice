import queue
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import App
from controls import KeyboardController, load_config
from test_controls import FakeKeyboard


class AppSafetyTests(unittest.TestCase):
    def setUp(self):
        # Exercise the real event/stop logic without opening a window or using input.
        self.app = App.__new__(App)
        self.app.root = Mock()
        self.app.windows = Mock()
        self.app.windows.f8_pressed.return_value = False
        self.app.config, self.app.phrases = load_config(Path(__file__).resolve().parents[1] / "config.json")
        self.keyboard = FakeKeyboard()
        self.app.controller = KeyboardController(self.keyboard, 30)
        self.app.events = queue.Queue()
        self.app.status = Mock()
        self.app.start_button = Mock()
        self.app.write_log = Mock()
        self.app.test_mode = Mock()
        self.app.test_mode.get.return_value = False
        self.app.session = 1
        self.app.stop_event = Mock()
        self.app.active = self.app.listening = True
        self.app.pending_start = False
        self.app.downloading = False
        self.app.f8_was_pressed = False
        self.app.worker = None

    def move(self):
        self.app.controller.execute(self.app.phrases["run"][1])
        self.assertEqual(self.keyboard.down, {"w", "shift"})
        self.app.controller.execute(self.app.phrases["shoot"][1])
        self.app.controller.execute(self.app.phrases["aim"][1])
        self.assertEqual(self.keyboard.down, {"w", "shift", "mouse1", "mouse2"})

    def test_f8_releases_keys_and_discards_queued_command(self):
        self.move()
        self.app.events.put((1, "command", "walk"))
        self.app.windows.f8_pressed.return_value = True
        self.app.poll()
        self.assertFalse(self.keyboard.down)
        self.assertFalse(self.app.listening)
        self.app.stop_event.set.assert_called_once()

    def test_commands_work_without_siege_or_a_focus_check(self):
        self.move()
        self.app.events.put((1, "command", "back"))
        self.app.poll()
        self.assertEqual(self.keyboard.down, {"s", "mouse1", "mouse2"})
        self.assertTrue(self.app.listening)
        self.app.windows.foreground_executable.assert_not_called()

    def test_commands_are_sent_without_checking_active_window(self):
        self.app.process_event(1, "command", "walk")
        self.assertEqual(self.keyboard.down, {"w"})
        self.app.windows.foreground_executable.assert_not_called()

    def test_f8_turns_on_when_stopped(self):
        self.app.stop()
        self.app.start = Mock()
        self.app.windows.f8_pressed.return_value = True
        self.app.poll()
        self.app.start.assert_called_once()

    def test_holding_f8_does_not_toggle_repeatedly(self):
        self.app.windows.f8_pressed.return_value = True
        self.app.poll()
        self.app.start = Mock()
        self.app.poll()
        self.app.poll()
        self.app.start.assert_not_called()
        self.app.windows.f8_pressed.return_value = False
        self.app.poll()
        self.app.windows.f8_pressed.return_value = True
        self.app.poll()
        self.app.start.assert_called_once()

    def test_quick_restart_waits_for_previous_microphone_worker(self):
        self.app.stop()
        self.app.worker = Mock()
        self.app.worker.is_alive.return_value = True
        self.app.start()
        self.assertTrue(self.app.pending_start)
        self.assertTrue(self.app.listening)
        self.assertFalse(self.app.active)
        self.app.start = Mock()
        self.app.poll()
        self.app.start.assert_not_called()
        self.app.worker.is_alive.return_value = False
        self.app.poll()
        self.app.start.assert_called_once()
        self.assertFalse(self.app.pending_start)

    def test_f8_cancels_pending_restart(self):
        self.app.pending_start = True
        self.app.active = False
        self.app.windows.f8_pressed.return_value = True
        self.app.poll()
        self.assertFalse(self.app.pending_start)
        self.assertFalse(self.app.listening)

    def test_ready_activates_without_countdown(self):
        self.app.active = False
        self.app.process_event(1, "ready", "Microphone ready")
        self.assertTrue(self.app.active)

    def test_test_mode_does_not_inject_keys(self):
        self.app.test_mode.get.return_value = True
        for phrase in ("run", "shoot", "aim"):
            self.app.process_event(1, "command", phrase)
        self.assertFalse(self.keyboard.events)

    def test_inactive_controls_ignore_commands(self):
        self.app.active = False
        self.app.process_event(1, "command", "walk")
        self.assertFalse(self.keyboard.events)

    def test_old_session_results_are_ignored(self):
        self.app.process_event(0, "command", "walk")
        self.assertFalse(self.keyboard.events)

    @patch("app.messagebox.showerror")
    def test_microphone_error_releases_keys(self, showerror):
        self.move()
        self.app.process_event(1, "error", "Microphone disconnected")
        self.assertFalse(self.keyboard.down)
        self.assertFalse(self.app.listening)
        showerror.assert_called_once()

    def test_close_releases_keys(self):
        self.move()
        self.app.close()
        self.assertFalse(self.keyboard.down)
        self.app.root.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
