"""Build a portable Windows app and ZIP, including an editable config and model."""

import json
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "SiegeButVoice"
MODEL = "vosk-model-small-en-us-0.15"


def main():
    if sys.platform != "win32":
        raise SystemExit("Build this Windows release on Windows.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", default="dist", help="Build output folder relative to this project")
    options = parser.parse_args()
    output_directory = (ROOT / options.output_directory).resolve()
    if not output_directory.is_relative_to(ROOT) or output_directory == ROOT:
        raise SystemExit("Build output must be a subfolder of this project.")
    if not (output_directory / NAME).resolve().is_relative_to(output_directory):
        raise SystemExit("The release folder must stay inside the build output folder.")
    model = ROOT / "models" / MODEL
    if not (model / "am" / "final.mdl").is_file():
        raise SystemExit("Download the default speech model in the app before building.")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--windowed", "--name", NAME, "--distpath", str(output_directory),
        "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
        "--collect-all", "vosk", "--collect-all", "_sounddevice_data",
        "--hidden-import", "_cffi_backend", str(ROOT / "app.py"),
    ], cwd=ROOT, check=True)
    release = output_directory / NAME
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    # Recipient picks their own microphone; always ship the model we include.
    config["microphone"] = None
    config["model_path"] = f"models/{MODEL}"
    (release / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    for filename in ("README.md", "DELIVERY.txt"):
        shutil.copy2(ROOT / filename, release / filename)
    shutil.copytree(model, release / "models" / MODEL, dirs_exist_ok=True)
    # Preserve bundled dependency licenses and package metadata for redistribution.
    from importlib.metadata import distributions
    licenses = release / "licenses"
    for package in distributions():
        for file in package.files or []:
            if any(word in file.name.lower() for word in ("license", "copying", "notice")):
                source = Path(package.locate_file(file))
                if source.is_file():
                    target = licenses / package.metadata["Name"] / file.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    archive = shutil.make_archive(str(output_directory / f"{NAME}-Windows-x64"), "zip",
                                  root_dir=output_directory, base_dir=NAME)
    print(f"Ready to send: {archive}")


if __name__ == "__main__":
    main()
