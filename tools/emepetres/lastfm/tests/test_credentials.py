import os
from pathlib import Path
import tempfile
import unittest

from lastfm.credentials import Vault, protect, unprotect


@unittest.skipUnless(os.name == "nt", "Windows DPAPI integration")
class CredentialsTests(unittest.TestCase):
    def test_dpapi_round_trip_does_not_write_plaintext_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Vault(Path(directory))
            self.assertEqual(vault.load(), {})
            payload = {"api_key": "TEST-ONLY-NOT-A-REAL-KEY", "secret": "TEST-ONLY-SECRET",
                       "sessions": {"alice": "TEST-ONLY-SESSION"}, "account": "Alice"}
            vault.save(payload)
            encrypted = vault.path.read_bytes()
            self.assertNotIn(b"TEST-ONLY", encrypted)
            self.assertEqual(vault.load(), payload)
            vault.path.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                vault.load()
            vault.clear()
            self.assertEqual(vault.load(), {})

    def test_unicode_and_empty_bytes_are_protected(self):
        for value in [b"", "sesión ficticia Björk".encode()]:
            self.assertEqual(unprotect(protect(value)), value)


if __name__ == "__main__":
    unittest.main()
