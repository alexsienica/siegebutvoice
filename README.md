# Voice Activated Siege

A small Windows Python app for playing Rainbow Six Siege with spoken keyboard
and mouse button commands. Mouse movement stays with you. Recognition
runs locally with Vosk; audio is not uploaded. **F8** toggles voice controls on
and off globally. Siege does not need to be open; commands send inputs to the
currently active window.

## Setup

Install **64-bit Python 3.11 or 3.12** from [python.org](https://www.python.org/downloads/windows/)
with pip and Tcl/Tk enabled. In PowerShell, open this folder and run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

If you installed Python 3.11, substitute `py -3.11` in the first command.
For subsequent launches, just run the last command or double-click `run.bat`.
No EXE is required.

1. Click **Download speech model** once. This downloads the approximately 40 MB
   [English Vosk model](https://alphacephei.com/vosk/models) into `models/`.
   Alternatively, download and extract `vosk-model-small-en-us-0.15` yourself.
2. Choose your microphone in the menu. **Refresh** finds newly connected devices.
   Changing microphones stops listening, and your selection is saved in `config.json`.
3. Keep **Test mode** checked and click **Start listening**. Say commands and check
   the activity log. Test mode does not press any keys or mouse buttons.
4. Stop, uncheck Test mode, select whichever window you want to control, and
   press **F8** to turn controls on. Commands work once the microphone is ready.
5. Speak one command at a time, with a brief pause afterward. Press **F8** again
   to turn controls off and release held keys and mouse buttons. Holding F8 toggles only once;
   release and press it again to toggle back on.

## Default commands

| Say | Input action |
| --- | --- |
| walk / forward | Hold W |
| back / backward | Hold S |
| left / right | Hold A / D |
| run / sprint | Hold W + Shift |
| shoot / fire | Hold Mouse 1 (left button) |
| stop shooting / cease fire | Release Mouse 1 |
| aim | Hold Mouse 2 (right button) |
| stop aiming / lower weapon | Release Mouse 2 |
| stop / freeze | Release all held keys and mouse buttons; keep listening |
| pause controls | Release all inputs and stop listening |
| reload | Tap R |
| crouch | Tap C |
| prone | Tap Ctrl |
| vault | Tap Space |
| lean left / lean right | Tap Q / E |
| interact / use | Tap F |
| gadget | Tap G |
| primary / secondary | Tap 1 / 2 |
| melee | Tap V |

Movement continues until `stop`, a replacement direction, or the hold timeout.
Forward/back/run replace each other; left/right replace each other. You can say
`walk`, then `left` to move diagonally. Say `walk` after `run` to stop sprinting.
Shooting and aiming can be held together, independently of movement. Use
hold-mode aiming in Siege so holding Mouse 2 aims down sights. The default
timeout releases held keys and mouse buttons after 30 seconds without a new hold command.
Turning controls off, closing the app, changing settings, and microphone errors
release keys and mouse buttons. Switching windows keeps controls on; press F8 whenever you want
to stop them.

These are starting key bindings: match the config to your Siege settings. Crouch,
prone, and lean assume the corresponding in-game controls use toggle mode.
Actions on other mouse buttons, including an ability on middle-click, stay manual;
rebind one to a keyboard key in Siege if you want to add a spoken command for it.

## Change commands

Click **Edit config**, save your changes, then click **Reload config**. Example:

```json
"walk": {
  "phrases": ["walk", "forward", "advance"],
  "action": "hold",
  "keys": ["w"],
  "group": "forward"
}
```

The object name is just a label; `phrases` contains the words you say. Phrases must
be unique. Common English words work best with the included English speech model.
Only complete recognized phrases are accepted, so `lean left` does not also
trigger `left`. Low-confidence or unknown speech appears as ignored in the log.

Supported actions:

- `hold`: hold `keys`, replacing any existing hold in the same `group`.
- `tap`: briefly press `keys`.
- `release`: release the named `group` (no `keys` needed).
- `stop`: release all keys and mouse buttons and keep listening.
- `pause`: release all keys and mouse buttons and stop listening.

For hold-mode interactions, add a pair such as:

```json
"interact": {"phrases": ["interact", "use"], "action": "hold", "keys": ["f"], "group": "interaction"},
"release_interact": {"phrases": ["release interaction"], "action": "release", "group": "interaction"}
```

Replace the existing `interact` entry rather than duplicating it. Keyboard keys
include letters, digits, `shift`, `ctrl`, `alt`, `space`, `tab`, `esc`, `enter`,
`backspace`, arrows, and F1–F12 except F8 (reserved for the global toggle).
Use `mouse1` and `mouse2` in `keys` for the left and right mouse buttons.
They support the same hold/tap/release actions, without moving the pointer:

```json
"shoot": {"phrases": ["shoot", "fire"], "action": "hold", "keys": ["mouse1"], "group": "shooting"},
"stop_shooting": {"phrases": ["stop shooting", "cease fire"], "action": "release", "group": "shooting"}
```

Other settings:

- `minimum_confidence`: 0–1; default 0.65. Increase it if commands trigger incorrectly.
- `max_hold_seconds`: 1–300; default 30.
- `model_path`: model directory, relative to this app or an absolute path.
- `microphone`: saved menu label, or `null` to select the system default.

## Troubleshooting and validation

Use headphones to keep game audio out of the microphone. If your microphone
does not appear, check Windows microphone permissions for desktop apps, connect
it, and click Refresh. If commands are ignored, speak clearly with a pause and
check Test mode before changing the confidence threshold.

Keyboard injection uses [PyDirectInput](https://github.com/learncodebygaming/pydirectinput).
Actual acceptance by Siege must be checked in your game; anti-cheat or game input
handling can reject synthetic keys. This app does not bypass those systems.
If Siege runs elevated, Windows can block input from a non-elevated app; run both
at the same permission level. Prefer testing in a private/custom match.

Run the automated state/configuration tests (no microphone, game, or injected
keystrokes required):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The speech implementation follows [Vosk's microphone example](https://github.com/alphacep/vosk-api/blob/master/python/example/test_microphone.py).
