"""Offline CLI contracts and optional real Tk window smoke checks."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lastfm import engine
from lastfm.__main__ import main


class CLI(unittest.TestCase):
    def test_preview_import_is_readonly_idempotent_and_account_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            log = folder / '.emepetres-scrobbler.log'
            data = b'#TZ/UTC\nArtist\tAlbum\tTrack\t1\t180\tL\t1700000000\n'
            log.write_bytes(data)
            args = ['--data-dir', str(folder / 'data'), 'preview', '--account', 'Alice', '--import', str(log)]
            with patch.object(engine.HTTPTransport, '__call__', side_effect=AssertionError('Network during preview')):
                first, second, other = io.StringIO(), io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(first):
                    self.assertEqual(main(args), 0)
                with contextlib.redirect_stdout(second):
                    self.assertEqual(main(args), 0)
                with contextlib.redirect_stdout(other):
                    self.assertEqual(main(['--data-dir', str(folder / 'data'), 'preview', '--account', 'Bob']), 0)
            self.assertEqual(log.read_bytes(), data)
            self.assertEqual(json.loads(first.getvalue())['counts'], {'pending': 1})
            self.assertEqual(json.loads(second.getvalue())['imports'][0]['duplicates'], 1)
            self.assertEqual(json.loads(other.getvalue())['rows'], [])

    def test_sync_without_authorized_account_never_calls_network(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('lastfm.credentials.Vault.load', return_value={'sessions': {'alice': 'private-session'}}):
                with patch.object(engine.HTTPTransport, '__call__', side_effect=AssertionError('Wrong-account network')):
                    with contextlib.redirect_stderr(io.StringIO()) as errors:
                        result = main(['--data-dir', directory, 'sync', '--account', 'bob'])
            self.assertEqual(result, 1)
            self.assertNotIn('private-session', errors.getvalue())

    def test_browser_failure_does_not_print_token_or_application_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            output, errors = io.StringIO(), io.StringIO()
            with patch('lastfm.__main__.getpass.getpass', side_effect=['sample-key', 'sample-secret']):
                with patch('lastfm.__main__.webbrowser.open', return_value=False):
                    with patch.object(engine.HTTPTransport, '__call__', return_value={'token': 'sample-token'}):
                        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                            result = main(['--data-dir', directory, 'connect'])
            self.assertEqual(result, 1)
            for value in ('sample-key', 'sample-secret', 'sample-token'):
                self.assertNotIn(value, output.getvalue() + errors.getvalue())


class WindowSmoke(unittest.TestCase):
    def test_window_starts_offline_and_displays_imported_rows(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display unavailable: {exc}')
        root.withdraw()
        try:
            from lastfm.gui import App
            with tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                log = folder / '.scrobbler.log'
                log.write_bytes(b'#TZ/UNKNOWN\nArtist\tAlbum\tTrack\t1\t180\tL\t1700000000\n'
                                b'#TZ/UTC\nArtist\tAlbum\tInterrupted track\t2\t180\tL\t1700000300\n')
                ledger = engine.Ledger(folder)
                try:
                    ledger.import_file(log, 'alice')
                    with ledger.connection:
                        ledger.connection.execute("UPDATE entries SET status='sending' WHERE track='Interrupted track'")
                finally:
                    ledger.close()
                with patch('lastfm.credentials.Vault.load', return_value={}):
                    with patch.object(engine.HTTPTransport, '__call__', side_effect=AssertionError('Network on launch')):
                        app = App(root, folder)
                        app.account.set('alice')
                        app.refresh()
                        root.update()
                        items = app.tree.get_children()
                        self.assertEqual(len(items), 2)
                        self.assertEqual(app.tree.item(items[0], 'values')[0], 'Para revisar')
                        self.assertEqual(app.tree.item(items[1], 'values')[0], 'Sin confirmar')
                        self.assertIn('Solo vista previa', app.connection.get())
                        root.after_cancel(app.poll_after)
                        app.closed = True
        finally:
            root.destroy()

    def test_background_import_and_explicit_sync_use_separate_sqlite_connections(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display unavailable: {exc}')
        root.withdraw()
        try:
            from lastfm.gui import App
            with tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                log = folder / '.emepetres-scrobbler.log'
                original = b'#TZ/UTC\nArtist\tAlbum\tTrack\t1\t180\tL\t1700000000\n'
                log.write_bytes(original)
                settings = {'account': 'alice', 'api_key': 'sample-key', 'secret': 'sample-secret',
                            'sessions': {'alice': 'sample-session'}}
                with patch('lastfm.credentials.Vault.load', return_value=settings):
                    app = App(root, folder)
                with patch('lastfm.gui.filedialog.askopenfilename', return_value=str(log)):
                    app.import_log()
                deadline = time.monotonic() + 5
                while app.busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                self.assertFalse(app.busy)
                self.assertEqual(len(app.tree.get_children()), 1)
                response = {'scrobbles': {'scrobble': {'timestamp': '1700000000', 'ignoredMessage': {'code': '0'}},
                                          '@attr': {'accepted': '1', 'ignored': '0'}}}
                with patch('lastfm.gui.messagebox.askyesno', side_effect=AssertionError('A deliberate sync click needs no second confirmation')):
                    with patch.object(engine.HTTPTransport, '__call__', return_value=response):
                        app.sync()
                        deadline = time.monotonic() + 5
                        while app.busy and time.monotonic() < deadline:
                            root.update()
                            time.sleep(0.01)
                self.assertFalse(app.busy)
                ledger = engine.Ledger(folder)
                try:
                    self.assertEqual(ledger.counts('alice'), {'sent': 1})
                finally:
                    ledger.close()
                self.assertEqual(log.read_bytes(), original)
                root.after_cancel(app.poll_after)
                app.closed = True
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
