#!/usr/bin/env python3
"""Puts the landing page on the update server, pointing at an installer already in the feed.

Run it on the Linux server: python3 website/deploy.py
It never changes anything under windows/, so it can't disturb app updates.
"""

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
SETUP_SCRIPT = HERE.parent / "desktop" / "linux" / "setup.sh"
NGINX_CONFIG = Path("/etc/nginx/conf.d/nexusai-updates.conf")
# Written by desktop/linux/setup.sh. Without it, the page returns 404 and stays cached for a year.
NGINX_MARKER = "index\\.html|release\\.js"
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,180}")
CHANNELS = {"pilot", "latest"}


class DeployError(Exception):
    pass


def load_config(path):
    try:
        config = json.loads(path.read_text())
    except FileNotFoundError:
        raise DeployError(f"{path} not found. Copy website/deploy.example.json to it and fill it in.")
    except json.JSONDecodeError as error:
        raise DeployError(f"{path} is not valid JSON: {error}")
    for key in ("version", "channel", "releaseRoot", "installerFolder", "port", "publicUrl"):
        if key not in config:
            raise DeployError(f"{path} is missing {key}.")
    if config["channel"] not in CHANNELS:
        raise DeployError('channel must be "pilot" or "latest".')
    if config["version"] != "latest" and not VERSION.fullmatch(config["version"]):
        raise DeployError('version must be three numbers, like 0.1.0, or "latest".')
    root = Path(config["releaseRoot"])
    if not root.is_absolute() or root == Path("/") or ".." in root.parts:
        raise DeployError("releaseRoot must be a dedicated absolute path, like /srv/nexusai-updates.")
    folder = PurePosixPath(config["installerFolder"])
    if folder.is_absolute() or ".." in folder.parts:
        raise DeployError("installerFolder must be relative to releaseRoot, like windows/x64/unsigned.")
    if not re.match(r"https?://[^/\s]+/?$", config["publicUrl"]) or "UPDATE-HOST" in config["publicUrl"]:
        raise DeployError("publicUrl must be this server's address, like http://nexus.example:8088.")
    if not isinstance(config["port"], int) or not 1 <= config["port"] <= 65535:
        raise DeployError("port must be a number from 1 to 65535.")
    return config


def current_version(feed, channel):
    pointer = feed / f"{channel}.yml"
    try:
        found = re.search(r"^version: ['\"]?([0-9.]+)['\"]?$", pointer.read_text(), re.M)
    except FileNotFoundError:
        raise DeployError(f'version is "latest", but {pointer} doesn\'t exist. Publish a release first.')
    if not found or not VERSION.fullmatch(found[1]):
        raise DeployError(f"Couldn't read the version in {pointer}.")
    return found[1]


def sha256(path):
    hashed = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


def find_release(config):
    """What the release tool published, checked against the file actually on disk."""
    feed = Path(config["releaseRoot"]) / config["installerFolder"]
    if not feed.is_dir():
        raise DeployError(f"Feed folder {feed} doesn't exist. Check releaseRoot and installerFolder.")
    version = current_version(feed, config["channel"]) if config["version"] == "latest" else config["version"]
    folder = feed / version
    if not folder.is_dir():
        raise DeployError(f"Version {version} isn't in {feed}. Publish it from the Windows build machine first.")
    manifest_file = folder / "release.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
    listed = [item for item in manifest.get("files", []) if item["name"].endswith(".exe")]
    if listed:
        name, expected = listed[0]["name"], listed[0]["sha256"]
    else:
        installers = sorted(path.name for path in folder.glob("*.exe"))
        if len(installers) != 1:
            raise DeployError(f"Expected one .exe in {folder}, found {len(installers)}.")
        name, expected = installers[0], None
    if not FILE_NAME.fullmatch(name):
        raise DeployError(f"Unsafe installer name: {name}")
    installer = folder / name
    if not installer.is_file():
        raise DeployError(f"{installer} is listed in release.json but missing.")
    digest = sha256(installer)
    if expected and digest != expected:
        raise DeployError(f"{installer} doesn't match its checksum in release.json. Publish it again.")
    relative = PurePosixPath(config["installerFolder"]) / version / name
    return {
        "version": version,
        "fileName": name,
        "url": urllib.parse.quote(str(relative)),
        "sizeBytes": installer.stat().st_size,
        "sha256": digest,
    }


def release_script(release):
    return "// Written by website/deploy.py.\nwindow.NEXUSAI_RELEASE = " + json.dumps(release, indent=2) + ";\n"


def write_atomically(target, content):
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".deploy-", dir=target.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def publish_page(config, release):
    root = Path(config["releaseRoot"])
    if not root.is_dir():
        raise DeployError(f"{root} doesn't exist. Run desktop.cmd server-setup first.")
    if not (root / ".nexusai-release-host").exists():
        raise DeployError(f"{root} wasn't set up by NexusAI server-setup, so I won't write to it.")
    # The page goes last, so nobody loads it before the files it needs are there.
    fonts = sorted((HERE / "fonts").glob("*.woff2"))
    if not fonts:
        raise DeployError("website/fonts is empty.")
    try:
        for font in fonts:
            write_atomically(root / "fonts" / font.name, font.read_bytes())
        write_atomically(root / "release.js", release_script(release).encode())
        write_atomically(root / "index.html", (HERE / "index.html").read_bytes())
    except PermissionError as error:
        raise DeployError(f"Can't write to {root}: {error}. Run as the user that owns it, not with sudo.")


def nginx_ready():
    try:
        return NGINX_MARKER in NGINX_CONFIG.read_text()
    except OSError:
        return False


def setup_nginx(config):
    """Reruns the one server setup script, so the page and the update feed share one Nginx config."""
    command = ["sudo", "bash", str(SETUP_SCRIPT), config["releaseRoot"], getpass.getuser(), str(config["port"])]
    if config.get("tlsCertificate") or config.get("tlsKey"):
        command += [config.get("tlsCertificate", ""), config.get("tlsKey", "")]
    if subprocess.run(command).returncode != 0:
        raise DeployError("Nginx setup failed. The message above says why.")


def fetch(url, method="GET"):
    request = urllib.request.Request(url, method=method, headers={"User-Agent": "nexusai-deploy"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, response.headers, response.read() if method == "GET" else b""


def verify(config, release):
    """Checks what a visitor gets, not just what's on disk."""
    base = config["publicUrl"].rstrip("/") + "/"
    try:
        status, headers, body = fetch(base)
        if status != 200 or b"NEXUSAI_RELEASE" not in body:
            raise DeployError(f"{base} didn't return the landing page.")
        if "no-cache" not in (headers.get("Cache-Control") or ""):
            raise DeployError(f"{base} can be cached, so visitors could keep an old page. Run with --setup-nginx.")
        _, _, script = fetch(base + "release.js")
        if release["sha256"].encode() not in script:
            raise DeployError(f"{base}release.js doesn't show this release. Check a proxy isn't caching it.")
        status, headers, _ = fetch(base + release["url"], "HEAD")
        if status != 200 or int(headers.get("Content-Length") or -1) != release["sizeBytes"]:
            raise DeployError(f"{base}{release['url']} isn't serving the full installer.")
    except OSError as error:
        raise DeployError(f"Couldn't reach {base}: {error}. Check publicUrl, Nginx and the firewall.")
    return base


def main():
    parser = argparse.ArgumentParser(description="Deploy the NexusAI landing page on the update server.")
    parser.add_argument("--config", type=Path, default=HERE / "deploy.json", help="default: website/deploy.json")
    parser.add_argument("--check", action="store_true", help="show what would be deployed and change nothing")
    parser.add_argument("--setup-nginx", action="store_true", help="update the Nginx config first, using sudo")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        release = find_release(config)
        size = round(release["sizeBytes"] / 1_000_000)
        print(f"Installer: {release['fileName']}, version {release['version']}, {size} MB, checksum OK")
        if args.check:
            print(f"Would be served from {config['publicUrl'].rstrip('/')}/{release['url']}")
            print("Nginx config: " + ("ready" if nginx_ready() else "needs --setup-nginx"))
            return 0
        if args.setup_nginx:
            setup_nginx(config)
        elif not nginx_ready():
            raise DeployError("The Nginx config doesn't serve the page yet. Run again with --setup-nginx.")
        publish_page(config, release)
        print("Live at " + verify(config, release))
    except DeployError as error:
        print(f"Deploy failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
