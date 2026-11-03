"""The git-ignored secrets file: present, partial, missing or broken."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spokebound import secret_config


class SecretConfigTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._path = Path(self._tmp.name) / "secrets.json"

    def _use(self, text: str | None) -> None:
        if text is not None:
            self._path.write_text(text, encoding="utf-8")
        patcher = patch.object(secret_config, "_SECRETS",
                               secret_config._load(self._path))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_file_turns_everything_off(self) -> None:
        self._use(None)
        self.assertIsNone(secret_config.relay_address())
        self.assertIsNone(secret_config.known_public_ip())

    def test_malformed_file_turns_everything_off(self) -> None:
        self._use("{ not json")
        self.assertIsNone(secret_config.relay_address())

    def test_non_object_json_turns_everything_off(self) -> None:
        self._use("[1, 2, 3]")
        self.assertIsNone(secret_config.relay_address())

    def test_full_file_is_read(self) -> None:
        self._use(json.dumps({"relay_host": "203.0.113.10",
                              "relay_port": 4000,
                              "known_public_ip": "198.51.100.7"}))
        self.assertEqual(secret_config.relay_address(),
                         ("203.0.113.10", 4000))
        self.assertEqual(secret_config.known_public_ip(), "198.51.100.7")

    def test_relay_port_defaults_when_omitted(self) -> None:
        self._use(json.dumps({"relay_host": "203.0.113.10"}))
        self.assertEqual(secret_config.relay_address(),
                         ("203.0.113.10", secret_config.DEFAULT_RELAY_PORT))

    def test_example_template_parses_and_names_only_known_keys(self) -> None:
        example = secret_config.SECRETS_PATH.with_name("secrets.example.json")
        data = json.loads(example.read_text(encoding="utf-8"))
        self.assertEqual(set(data),
                         {"relay_host", "relay_port", "known_public_ip"})


if __name__ == "__main__":
    unittest.main()
