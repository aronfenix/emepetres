"""Read-only discovery against temporary cards and substituted Windows APIs."""
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class Discovery(unittest.TestCase):
    def test_dedicated_export_wins_per_root_and_legacy_is_fallback(self):
        from lastfm import device
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preferred = root / '.emepetres-scrobbler.log'
            legacy = [root / '.scrobbler.log', root / '.scrobbler-timeless.log']
            for file in [preferred, *legacy]:
                file.write_bytes(b'unchanged\r\n')
            self.assertEqual(device.find_exports([root]), [preferred])
            preferred.unlink()
            self.assertEqual(device.find_exports([root]), legacy)

    def test_multiple_cards_missing_media_and_duplicates(self):
        from lastfm import device
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = root / 'a', root / 'b'
            a.mkdir(); b.mkdir()
            files = [a / '.emepetres-scrobbler.log', b / '.scrobbler.log']
            for file in files:
                file.touch()
            self.assertEqual(device.find_exports([a, root / 'removed', b, a]), files)
            files[0].unlink()
            self.assertEqual(device.find_exports([a]), [])

    def test_discovery_never_opens_exports_writes_or_scans_children(self):
        from lastfm import device
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / '.emepetres-scrobbler.log'
            log.write_bytes(b'exact\r\n')
            music = root / 'Music'
            music.mkdir()
            (music / '.scrobbler.log').touch()
            with patch.object(Path, 'open', side_effect=AssertionError('Opened file')), \
                    patch.object(Path, 'iterdir', side_effect=AssertionError('Listed music')), \
                    patch.object(Path, 'glob', side_effect=AssertionError('Globbed music')), \
                    patch.object(Path, 'rglob', side_effect=AssertionError('Scanned music')):
                self.assertEqual(device.find_exports([root]), [log])
            self.assertEqual(log.read_bytes(), b'exact\r\n')
            log.unlink()
            self.assertEqual(device.find_exports([root]), [])

    def test_unc_device_and_relative_paths_are_rejected_before_stat(self):
        from lastfm import device
        with patch.object(Path, 'lstat', side_effect=AssertionError('Touched untrusted root')):
            self.assertEqual(device.find_exports([r'\\server\share', r'\\?\UNC\server\share',
                                                  r'\\.\device', 'relative', r'Z:relative']), [])

    def test_root_and_export_reparse_points_are_not_followed(self):
        from lastfm import device
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / '.emepetres-scrobbler.log'
            log.touch()
            original = Path.lstat
            for replaced in (root, log):
                def marked(path, *args, **kwargs):
                    if path == replaced:
                        return SimpleNamespace(st_mode=stat.S_IFDIR if path == root else stat.S_IFREG,
                                               st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
                    return original(path, *args, **kwargs)
                with patch.object(Path, 'lstat', marked):
                    self.assertEqual(device.find_exports([root]), [])

    def test_only_windows_removable_drives_are_returned_without_stat(self):
        from lastfm import device
        # No real volume APIs or paths are consulted.
        api = SimpleNamespace(GetLogicalDrives=lambda: 0b11100,
                              GetDriveTypeW=lambda root: {'C:\\': 3, 'D:\\': 2, 'E:\\': 4}[root])
        with patch.object(device, '_windows_api', return_value=api), \
                patch.object(Path, 'lstat', side_effect=AssertionError('Probed volume')):
            self.assertEqual(device.removable_roots(), [Path('D:/')])


if __name__ == '__main__':
    unittest.main(verbosity=2)
