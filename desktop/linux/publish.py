"""Verify a complete staged release, then atomically advance one update channel."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys


def version(value):
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("Invalid release version")
    return tuple(map(int, value.split(".")))


def publish(root, stage, channel):
    if channel not in {"pilot", "latest"}:
        raise ValueError("Invalid channel")
    root, stage = Path(root).resolve(), Path(stage).resolve()
    if stage.parent != root / ".incoming":
        raise ValueError("Invalid staging location")
    manifest = json.loads((stage / "release.json").read_text())
    wanted = version(manifest["version"])
    if channel == "latest" and not manifest["signed"]:
        raise ValueError("Unsigned builds cannot be published to stable")
    if channel == "latest" and not manifest.get("updateBaseUrl", "").startswith("https://"):
        raise ValueError("Stable updates require HTTPS")
    files = manifest["files"]
    if not files or len({item["name"] for item in files}) != len(files):
        raise ValueError("Invalid file manifest")
    for item in files:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,180}", item["name"]):
            raise ValueError("Invalid filename")
        source = stage / item["name"]
        with source.open("rb") as stream:
            hashed = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hashed.update(chunk)
            digest = hashed.hexdigest()
            os.fsync(stream.fileno())
        if source.stat().st_size != item["size"] or digest != item["sha256"]:
            raise ValueError("Uploaded artifact is corrupt: " + item["name"])
        source.chmod(0o644)
    metadata = (stage / "channel.yml").read_text()
    if hashlib.sha256(metadata.encode()).hexdigest() != manifest.get("channelSha256"):
        raise ValueError("Uploaded channel metadata is corrupt")
    if not re.search(r"^version: ['\"]?" + re.escape(manifest["version"]) + r"['\"]?$", metadata, re.M):
        raise ValueError("Channel metadata version mismatch")
    with (root / ".publish.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pointer = root / (channel + ".yml")
        if pointer.exists():
            current = re.search(r"^version: ['\"]?([0-9.]+)['\"]?$", pointer.read_text(), re.M)
            if not current:
                raise ValueError("Cannot read existing channel version")
            if version(current[1]) > wanted:
                raise ValueError("Refusing to move an update channel backwards")
        target = root / manifest["version"]
        if target.exists():
            if (target / "release.json").read_bytes() != (stage / "release.json").read_bytes():
                raise ValueError("This version already exists with different artifacts; increase the version")
            # A previous interrupted publish may have moved the directory but not the channel.
            import shutil

            shutil.rmtree(stage)
        else:
            (stage / "publish.py").unlink(missing_ok=True)
            stage.chmod(0o755)
            os.rename(stage, target)
        temporary = root / ("." + channel + ".yml.tmp")
        temporary.write_text(metadata)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, pointer)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    print("Published", manifest["version"], "to", channel)


if __name__ == "__main__":
    publish(*sys.argv[1:])
