"""Offline recognition on a worker thread. It never sends keyboard input."""

import json
import queue
import time


def listen(device, model_path, phrases, minimum_confidence, stop, emit):
    try:
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        model = Model(str(model_path))
        if stop.is_set():
            return
        sample_rate = int(sd.query_devices(device, "input")["default_samplerate"])
        recognizer = KaldiRecognizer(model, sample_rate, json.dumps([*phrases, "[unk]"]))
        recognizer.SetWords(True)
        audio = queue.Queue(maxsize=20)

        def callback(data, frames, timing, status):
            if status:
                emit("error", f"Microphone stream interrupted: {status}")
                stop.set()
                return
            try:
                audio.put_nowait((time.monotonic(), bytes(data)))
            except queue.Full:
                emit("error", "Microphone processing fell behind. Listening stopped.")
                stop.set()

        with sd.RawInputStream(
            samplerate=sample_rate, blocksize=int(sample_rate * 0.1),
            device=device, dtype="int16", channels=1, callback=callback,
        ):
            emit("ready", "Microphone ready")
            while not stop.is_set():
                try:
                    timestamp, data = audio.get(timeout=0.15)
                except queue.Empty:
                    continue
                if time.monotonic() - timestamp > 1:
                    raise RuntimeError("Microphone audio is delayed. Listening stopped.")
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").strip()
                    words = result.get("result", [])
                    if not text:
                        continue
                    confidence = min((word.get("conf", 0) for word in words), default=0)
                    if text in phrases and confidence >= minimum_confidence:
                        emit("command", text)
                    else:
                        emit("heard", text)
    except Exception as error:
        emit("error", str(error))
    finally:
        emit("finished", "Listening ended")
