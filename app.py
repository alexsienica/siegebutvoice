"""Voice Activated Siege: run with python app.py on Windows."""

import json
import os
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.request
import zipfile
from pathlib import Path
from tkinter import messagebox, ttk

from controls import KeyboardController, load_config, normalize
from voice import listen

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


class App:
    def __init__(self, root, sounddevice, keyboard, windows):
        self.root = root
        self.sd = sounddevice
        self.keyboard = keyboard
        self.windows = windows
        self.events = queue.Queue()
        self.session = 0
        self.worker = None
        self.stop_event = None
        self.active = False
        self.listening = False
        self.pending_start = False
        self.f8_was_pressed = False
        self.downloading = False
        self.devices = {}
        self.config = None
        self.phrases = {}
        self.controller = KeyboardController(keyboard, 30)
        self.status = tk.StringVar(value="Stopped")
        self.microphone = tk.StringVar()
        self.test_mode = tk.BooleanVar(value=True)
        self._build_ui()
        self.reload_config()
        self.refresh_devices()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(40, self.poll)

    def _build_ui(self):
        self.root.title("Voice Activated Siege")
        self.root.geometry("720x700")
        self.root.minsize(600, 580)
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Voice Activated Siege", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Voice handles keys, shooting, and aim. You move the mouse.").pack(anchor="w", pady=(4, 16))
        ttk.Label(frame, text="Microphone").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(4, 10))
        self.mic_menu = ttk.Combobox(row, textvariable=self.microphone, state="readonly")
        self.mic_menu.pack(side="left", fill="x", expand=True)
        self.mic_menu.bind("<<ComboboxSelected>>", self.change_microphone)
        ttk.Button(row, text="Refresh", command=self.refresh_devices).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(frame, text="Test mode — recognize commands without pressing keys or mouse buttons",
                        variable=self.test_mode, command=self.stop).pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.start_button = ttk.Button(row, text="Start listening (F8)", command=self.start)
        self.start_button.pack(side="left")
        ttk.Button(row, text="Stop / release inputs", command=self.stop).pack(side="left", padx=8)
        ttk.Label(frame, textvariable=self.status, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(12, 6))
        ttk.Label(frame, text="Say one command, then pause briefly. Say 'stop' to release all inputs.").pack(anchor="w")
        ttk.Label(frame, text="F8 toggles controls globally. Commands go to whichever window is active.").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=12)
        ttk.Button(row, text="Edit config", command=lambda: os.startfile(CONFIG)).pack(side="left")
        ttk.Button(row, text="Reload config", command=self.reload_config).pack(side="left", padx=8)
        self.download_button = ttk.Button(row, text="Download speech model", command=self.download_model)
        self.download_button.pack(side="left")
        guide_frame = ttk.Frame(frame)
        guide_frame.pack(fill="both", expand=True)
        self.guide = ttk.Treeview(guide_frame, columns=("phrases", "action"), show="headings", height=10)
        self.guide.heading("phrases", text="Say")
        self.guide.heading("action", text="Action")
        self.guide.column("phrases", width=260)
        self.guide.column("action", width=260)
        self.guide.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(guide_frame, orient="vertical", command=self.guide.yview)
        scrollbar.pack(side="right", fill="y")
        self.guide.configure(yscrollcommand=scrollbar.set)
        ttk.Label(frame, text="Activity").pack(anchor="w", pady=(12, 4))
        self.log = tk.Text(frame, height=5, state="disabled", wrap="word", font=("Consolas", 9))
        self.log.pack(fill="x")

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        if int(self.log.index("end-1c").split(".")[0]) > 150:
            self.log.delete("1.0", "30.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def release_keys(self):
        try:
            self.controller.release_all()
            return True
        except Exception as error:
            self.write_log(str(error))
            return False

    def stop(self):
        self.active = False
        self.listening = False
        self.pending_start = False
        self.session += 1  # Discard results still queued by an earlier listener.
        if self.stop_event:
            self.stop_event.set()
        released = self.release_keys()
        self.status.set("Off — F8 turns controls on" if released else "Input release failed — release held keys/buttons manually")
        self.start_button.configure(state="normal")

    def toggle(self):
        if self.listening:
            self.stop()
            self.write_log("Voice controls off (F8). Keys and mouse buttons released.")
        else:
            self.start()

    def reload_config(self):
        self.stop()
        try:
            config, phrases = load_config(CONFIG)
            self.config, self.phrases = config, phrases
            self.controller.max_hold_seconds = config["max_hold_seconds"]
            self.guide.delete(*self.guide.get_children())
            for command in config["commands"].values():
                action = command["action"]
                description = f"{action}: {' + '.join(command.get('keys', []))}" if action in {"hold", "tap"} else action
                self.guide.insert("", "end", values=(", ".join(command["phrases"]), description))
            self.write_log("Configuration loaded.")
        except Exception as error:
            self.config = None
            self.phrases = {}
            messagebox.showerror("Configuration error", str(error))

    def refresh_devices(self):
        self.stop()
        try:
            devices = self.sd.query_devices()
            apis = self.sd.query_hostapis()
            self.devices = {
                f"{d['name']} [{apis[d['hostapi']]['name']}] #{i}": i
                for i, d in enumerate(devices) if d["max_input_channels"] > 0
            }
            self.mic_menu["values"] = list(self.devices)
            saved = self.config.get("microphone") if self.config else None
            if saved in self.devices:
                self.microphone.set(saved)
            elif self.microphone.get() not in self.devices:
                default = self.sd.default.device[0]
                selected = next((label for label, index in self.devices.items() if index == default), "")
                self.microphone.set(selected or next(iter(self.devices), ""))
            if not self.devices:
                self.status.set("No microphone found — connect one and click Refresh")
        except Exception as error:
            self.devices = {}
            self.mic_menu["values"] = []
            self.microphone.set("")
            messagebox.showerror("Microphone error", str(error))

    def change_microphone(self, event=None):
        self.stop()
        if self.config:
            try:
                # Read the file again so un-reloaded manual edits are preserved.
                config, _ = load_config(CONFIG)
                config["microphone"] = self.microphone.get()
                temporary = CONFIG.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
                temporary.replace(CONFIG)
                self.config["microphone"] = config["microphone"]
                self.write_log("Microphone selected. Click Start to listen again.")
            except Exception as error:
                messagebox.showerror("Could not save microphone", str(error))

    def start(self):
        if self.listening:
            return
        if self.downloading:
            self.status.set("Wait for the speech model download to finish")
            return
        if self.worker and self.worker.is_alive():
            self.pending_start = True
            self.listening = True
            self.start_button.configure(state="disabled")
            self.status.set("Restarting microphone… F8 cancels")
            return
        if not self.config:
            messagebox.showerror("Configuration", "Fix config.json and click Reload config.")
            return
        device = self.devices.get(self.microphone.get())
        if device is None:
            messagebox.showerror("Microphone", "Select a working microphone first.")
            return
        model = ROOT / self.config["model_path"]
        if not (model / "am" / "final.mdl").is_file():
            messagebox.showinfo("Speech model needed", "Click Download speech model first, or set model_path to an extracted Vosk model.")
            return
        self.stop()
        self.listening = True
        self.stop_event = threading.Event()
        session = self.session
        self.status.set("Loading speech model…")
        self.start_button.configure(state="disabled")
        self.worker = threading.Thread(
            target=listen, args=(device, model, self.phrases, self.config["minimum_confidence"],
                                self.stop_event, lambda kind, text: self.events.put((session, kind, text))),
            daemon=True,
        )
        self.worker.start()

    def process_event(self, session, kind, text):
        if session == "download":
            if kind == "done":
                self.downloading = False
                self.download_button.configure(state="normal")
                self.status.set(text)
                self.write_log(text)
            elif kind == "error":
                self.downloading = False
                self.download_button.configure(state="normal")
                self.status.set("Model download failed")
                messagebox.showerror("Model download", text)
            return
        if session != self.session:
            return
        if kind == "ready":
            self.active = True
            self.status.set("Test mode — F8 turns controls off" if self.test_mode.get() else "On — F8 turns controls off")
        elif kind == "error":
            self.stop()
            self.status.set("Listening stopped after an error")
            self.write_log(text)
            messagebox.showerror("Listening error", text)
        elif kind == "finished":
            self.stop()
        elif kind == "heard":
            self.write_log(f"Ignored: {text}")
        elif kind == "command" and self.active:
            name, command = self.phrases[normalize(text)]
            if command["action"] == "pause":
                self.stop()
                self.write_log("Voice controls paused. Press F8 to resume.")
            elif self.test_mode.get():
                self.write_log(f"TEST: {text} -> {name}")
            else:
                self.controller.execute(command)
                self.write_log(f"{text} -> {name}")

    def poll(self):
        try:
            pressed = self.windows.f8_pressed()
            was_pressed = self.f8_was_pressed
            self.f8_was_pressed = pressed
            if pressed and not was_pressed:
                self.toggle()
            if self.pending_start and not self.worker.is_alive():
                self.pending_start = False
                self.listening = False
                self.start()
            # Bound event work so F8 and releases get serviced even under load.
            for _ in range(40):
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                self.process_event(*event)
            if self.controller.tick():
                self.write_log("Hold timed out — held keys and mouse buttons released.")
        except Exception as error:
            self.stop()
            self.write_log(f"Controls stopped: {error}")
        self.root.after(40, self.poll)

    def download_model(self):
        if self.downloading:
            return
        self.stop()
        self.downloading = True
        self.download_button.configure(state="disabled")
        self.status.set("Downloading English speech model (~40 MB)…")

        def download():
            try:
                target = ROOT / "models"
                target.mkdir(exist_ok=True)
                if not (target / MODEL_NAME / "am" / "final.mdl").is_file():
                    with tempfile.TemporaryDirectory(dir=target) as temporary:
                        archive = Path(temporary) / "model.zip"
                        with urllib.request.urlopen(MODEL_URL, timeout=30) as response, archive.open("wb") as output:
                            while chunk := response.read(1024 * 1024):
                                output.write(chunk)
                        with zipfile.ZipFile(archive) as zipped:
                            base = Path(temporary).resolve()
                            for member in zipped.infolist():
                                if not (base / member.filename).resolve().is_relative_to(base):
                                    raise ValueError("Unsafe path in downloaded model archive.")
                            zipped.extractall(temporary)
                        extracted = Path(temporary) / MODEL_NAME
                        if not (extracted / "am" / "final.mdl").is_file():
                            raise ValueError("Downloaded archive does not contain the expected model.")
                        extracted.rename(target / MODEL_NAME)
                self.events.put(("download", "done", f"Speech model ready: models/{MODEL_NAME}"))
            except Exception as error:
                self.events.put(("download", "error", str(error)))

        threading.Thread(target=download, daemon=True).start()

    def close(self):
        self.stop()
        self.root.destroy()


def main():
    if sys.platform != "win32":
        raise SystemExit("Voice Activated Siege currently supports Windows only.")
    root = tk.Tk()
    try:
        import sounddevice
        import pydirectinput
        import vosk  # Check the dependency before opening the app.
        from windows_input import WindowsState

        # Mouse movement remains manual. A mouse corner must not block input releases.
        pydirectinput.FAILSAFE = False
        pydirectinput.PAUSE = 0
        App(root, sounddevice, pydirectinput, WindowsState())
    except Exception as error:
        messagebox.showerror("Startup error", f"{error}\n\nInstall dependencies with: python -m pip install -r requirements.txt")
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
