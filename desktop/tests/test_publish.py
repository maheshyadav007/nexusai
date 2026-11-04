"""Exercise the actual Linux publication script against temporary release directories."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("publish", Path(__file__).parents[1] / "linux/publish.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / ".incoming").mkdir()
        self.counter = 0

    def stage(self, version="0.1.0", signed=False, body=b"installer"):
        self.counter += 1
        directory = self.root / ".incoming" / str(self.counter)
        directory.mkdir(mode=0o700)
        files = []
        for name, content in [("Setup.exe", body), ("latest.yml", b"builder metadata")]:
            (directory / name).write_bytes(content)
            files.append({"name": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        metadata = f"version: {version}\nfiles: []\n"
        (directory / "release.json").write_text(json.dumps({"version": version, "signed": signed,
            "updateBaseUrl": "https://example.com/windows/x64/", "files": files,
            "channelSha256": hashlib.sha256(metadata.encode()).hexdigest()}))
        (directory / "channel.yml").write_text(metadata)
        return directory

    def test_complete_release_is_readable_and_channel_moves_last(self):
        module.publish(self.root, self.stage(), "pilot")
        self.assertEqual((self.root / "pilot.yml").read_text(), "version: 0.1.0\nfiles: []\n")
        self.assertEqual((self.root / "0.1.0/Setup.exe").read_bytes(), b"installer")
        self.assertEqual((self.root / "0.1.0").stat().st_mode & 0o777, 0o755)

    def test_corruption_preserves_current_release(self):
        module.publish(self.root, self.stage(), "pilot")
        broken = self.stage("0.1.1")
        (broken / "Setup.exe").write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "corrupt"):
            module.publish(self.root, broken, "pilot")
        self.assertIn("0.1.0", (self.root / "pilot.yml").read_text())
        self.assertFalse((self.root / "0.1.1").exists())

    def test_retry_is_idempotent_but_same_version_cannot_change(self):
        module.publish(self.root, self.stage(), "pilot")
        module.publish(self.root, self.stage(), "pilot")
        with self.assertRaisesRegex(ValueError, "different artifacts"):
            module.publish(self.root, self.stage(body=b"different"), "pilot")

    def test_downgrade_and_unsigned_stable_are_rejected(self):
        module.publish(self.root, self.stage("0.2.0"), "pilot")
        with self.assertRaisesRegex(ValueError, "backwards"):
            module.publish(self.root, self.stage(), "pilot")
        with self.assertRaisesRegex(ValueError, "Unsigned"):
            module.publish(self.root, self.stage(), "latest")

    def test_signed_promotion_reuses_existing_artifacts(self):
        module.publish(self.root, self.stage(signed=True), "pilot")
        module.publish(self.root, self.stage(signed=True), "latest")
        self.assertEqual((self.root / "pilot.yml").read_text(), (self.root / "latest.yml").read_text())

    def test_corrupted_channel_metadata_never_advances_the_feed(self):
        module.publish(self.root, self.stage(), "pilot")
        damaged = self.stage("0.1.1")
        (damaged / "channel.yml").write_text("version: 0.1.1\nfiles: [wrong]\n")
        with self.assertRaisesRegex(ValueError, "metadata is corrupt"):
            module.publish(self.root, damaged, "pilot")
        self.assertIn("0.1.0", (self.root / "pilot.yml").read_text())


if __name__ == "__main__":
    unittest.main()
