import os
import sys
import unittest
from uuid import uuid4
from unittest.mock import Mock, patch

from maho import credentials
from maho.cli import main


class MacCredentialTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.platform = patch.object(credentials.sys, "platform", "darwin")
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.native_backend = patch.object(credentials, "_mac_keychain", return_value=self.backend)
        self.platform.start()
        self.environment.start()
        self.native_backend.start()
        self.addCleanup(self.platform.stop)
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.native_backend.stop)

    def test_services_are_stored_separately_and_can_be_read_again(self):
        stored = {}
        self.backend.set_password.side_effect = lambda service, user, key: stored.update({(service, user): key})
        self.backend.get_password.side_effect = lambda service, user: stored.get((service, user))
        credentials.save_key(" test-only-assemblyai ", "assemblyai")
        credentials.save_key("test-only-openai", "openai")
        self.assertEqual(credentials.get_key("assemblyai"), "test-only-assemblyai")
        self.assertEqual(credentials.get_key("openai"), "test-only-openai")
        self.assertEqual(len(stored), 2)

    def test_environment_takes_precedence_without_accessing_keychain(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only-environment"}):
            self.assertEqual(credentials.get_key("openai"), "test-only-environment")
        self.backend.get_password.assert_not_called()

    def test_denied_keychain_access_does_not_disclose_provider_error_or_key(self):
        for operation in ("get", "save"):
            with self.subTest(operation=operation):
                self.backend.get_password.side_effect = RuntimeError("Rejected test-only-secret")
                self.backend.set_password.side_effect = RuntimeError("Rejected test-only-secret")
                with self.assertRaises(RuntimeError) as error:
                    if operation == "get":
                        credentials.get_key("openai")
                    else:
                        credentials.save_key("test-only-secret", "openai")
                self.assertNotIn("test-only-secret", str(error.exception))
                self.assertIn("keychain", str(error.exception).lower())

    def test_missing_key_gives_setup_command(self):
        self.backend.get_password.return_value = None
        with self.assertRaisesRegex(RuntimeError, "maho set-key --service openai"):
            credentials.get_key("openai")

    def test_invalid_keys_and_services_never_touch_keychain(self):
        for key, service in (("", "openai"), ("x" * 2561, "openai"), ("test-only-secret", "unknown")):
            with self.assertRaises(ValueError):
                credentials.save_key(key, service)
        self.backend.set_password.assert_not_called()
        with self.assertRaises(ValueError):
            credentials.get_key("unknown")
        self.backend.get_password.assert_not_called()

    def test_cli_uses_hidden_input_and_reports_mac_storage(self):
        with patch("maho.cli.getpass.getpass", return_value="test-only-openai") as hidden_input, patch("builtins.print") as output:
            self.assertEqual(main(["set-key", "--service", "openai"]), 0)
        hidden_input.assert_called_once()
        self.backend.set_password.assert_called_once_with("Maho/OpenAI", "Maho", "test-only-openai")
        output.assert_called_with("API key saved in macOS Keychain for openai.")


@unittest.skipUnless(sys.platform == "darwin", "Requires the native macOS Keychain")
class NativeMacKeychainTests(unittest.TestCase):
    def test_native_keychain_round_trip_for_both_services(self):
        namespace = f"Maho/Test/{uuid4()}"
        backend = credentials._mac_keychain()
        saved = []
        with patch.dict(os.environ, {}, clear=True), patch.object(credentials, "TARGET", namespace + "/AssemblyAI"), patch.object(credentials, "OPENAI_TARGET", namespace + "/OpenAI"):
            try:
                for service, target in (("assemblyai", credentials.TARGET), ("openai", credentials.OPENAI_TARGET)):
                    credentials.save_key("test-only-keychain-value", service)
                    saved.append(target)
                    self.assertEqual(credentials.get_key(service), "test-only-keychain-value")
            finally:
                for target in saved:
                    backend.delete_password(target, "Maho")


if __name__ == "__main__":
    unittest.main()
