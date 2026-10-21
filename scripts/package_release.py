"""Create a source-only ZIP from an explicit allowlist, without local data."""
from pathlib import Path
import argparse
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = ("README.md", "TEAM_SETUP.md", "Dockerfile", "compose.yaml", ".dockerignore", ".gitignore",
             ".env.example", "requirements.txt", "requirements.lock.txt", "requirements-model.txt",
             "setup.ps1", "start.ps1", "evaluate_voicescope.py")
DIRECTORIES = ("backend", "dist", "docs", "tests", "scripts", "plugins")


def release_files(root: Path):
    root = root.resolve()
    files = [root / name for name in TOP_LEVEL]
    for directory in DIRECTORIES:
        base = root / directory
        if base.is_symlink():
            raise ValueError(f"Release directory must not be a symlink: {directory}")
        for item in sorted(base.rglob("*")):
            if item.is_symlink():
                raise ValueError("Release sources must not contain symlinks")
            if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc":
                files.append(item)
    files.append(root / "models/README.md")
    for item in files:
        if item.is_symlink() or not item.resolve().is_relative_to(root) or not item.is_file():
            raise ValueError(f"Missing or unsafe release source: {item.name}")
        # These never belong in a code handoff, including inside plugins/.
        if item.name == ".env" or any(part in {".git", ".openai", ".venv", ".runtime", "artifacts"} for part in item.relative_to(root).parts):
            raise ValueError("Private runtime/configuration file found in release sources")
        if item.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".mov", ".mkv", ".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".bin", ".zip"}:
            raise ValueError(f"Media/model/archive file does not belong in a source release: {item.name}")
    return sorted(set(files))


def build_release(root: Path, destination: Path):
    root = root.resolve()
    files = release_files(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in files:
            relative = item.relative_to(root).as_posix()
            entry = zipfile.ZipInfo(f"voice-scope/{relative}", date_time=(2026, 10, 12, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, item.read_bytes())
    temporary.replace(destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix(".zip.sha256")
    checksum.write_text(f"{digest}  {destination.name}\n", encoding="utf-8")
    print(f"Source ZIP: {destination}")
    print(f"Files: {len(files)} | SHA256: {digest}")
    return destination


def main():
    parser = argparse.ArgumentParser(description="Package the local app for teammates")
    parser.add_argument("--output", type=Path, default=ROOT / "release/VoiceScope-localhost.zip")
    args = parser.parse_args()
    build_release(ROOT, args.output.resolve())


if __name__ == "__main__":
    main()
