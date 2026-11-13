"""Portable checks for the disposable FLAC fixture; no audio tools required."""
import struct
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from library_fixture import library_tracks, replace_comments, split_flac
from simulator_library_smoke import database_status, initialize


def block(kind, payload, last=False):
    return bytes([kind | (128 if last else 0)]) + len(payload).to_bytes(3, 'big') + payload


class LibraryFixture(unittest.TestCase):
    def test_comments_preserve_streaminfo_and_audio_frames(self):
        original = b'fLaC' + block(0, bytes(34)) + block(4, b'old', True) + b'\xff\xf8frames'
        rewritten = replace_comments(original, {'ARTIST': 'Aster', 'TITLE': 'Ámber'})
        metadata, frames = split_flac(rewritten)
        self.assertEqual(metadata[0], (0, bytes(34)))
        self.assertEqual(frames, b'\xff\xf8frames')
        self.assertEqual([kind for kind, _ in metadata], [0, 4])
        comments = metadata[1][1]
        size = struct.unpack_from('<I', comments)[0]
        offset = 4 + size
        count = struct.unpack_from('<I', comments, offset)[0]
        offset += 4
        values = []
        for _ in range(count):
            size = struct.unpack_from('<I', comments, offset)[0]
            offset += 4
            values.append(comments[offset:offset + size].decode('utf-8'))
            offset += size
        self.assertEqual(values, ['ARTIST=Aster', 'TITLE=Ámber'])
        self.assertEqual(offset, len(comments))

    def test_rejects_truncated_metadata_and_non_flac(self):
        for raw in (b'not flac', b'fLaC\x80\0\0\x22short'):
            with self.assertRaises(ValueError):
                replace_comments(raw, {'ARTIST': 'Aster'})

    def test_large_fixture_has_collision_and_adversarial_multidisc_order(self):
        tracks = list(library_tracks())
        self.assertEqual(len(tracks), 2054)
        self.assertEqual(len({tags['ARTIST'] for _, tags in tracks}), 258)
        self.assertEqual(len({tags['ALBUM'] for _, tags in tracks}), 258)
        echo = [tags for _, tags in tracks if tags['ALBUM'] == 'Echo']
        self.assertEqual({tags['ARTIST'] for tags in echo}, {'Aster', 'Zulu'})
        delta = [tags for _, tags in tracks if tags['ALBUM'] == 'Delta']
        self.assertEqual([tags['TITLE'] for tags in delta], ['Four', 'Three', 'Two', 'One'])
        self.assertEqual([tags['TITLE'] for tags in sorted(delta, key=lambda t: (int(t['DISCNUMBER']), int(t['TRACKNUMBER'])))],
                         ['One', 'Two', 'Three', 'Four'])
        for field, expected in [('ARTIST', {'Aster'}), ('ALBUM', {'Delta'}), ('TITLE', {'Amber'})]:
            self.assertEqual({tags[field] for _, tags in tracks if 'a' in tags[field].lower()}, expected)

    def test_database_header_diagnostics_distinguish_complete_partial_and_bad_magic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / '.rockbox'
            database.mkdir()
            (database / 'database_tmp.tcd').write_bytes(struct.pack('<III', 0x54434810, 123, 2054))
            (database / 'database_idx.tcd').write_bytes(struct.pack('>IIIIII', 0x54434810, 456, 2054, 0, 1, 0))
            (database / 'database_partial.tcd').write_bytes(b'\x10\x48\x43\x54short')
            (database / 'database_bad.tcd').write_bytes(struct.pack('<III', 0, 123, 2054))
            status = database_status(root)
            self.assertEqual(status['database_tmp.tcd']['indexed_tracks'], 2054)
            self.assertEqual(status['database_tmp.tcd']['byteorder'], '<')
            self.assertEqual(status['database_idx.tcd']['indexed_tracks'], 2054)
            self.assertEqual(status['database_idx.tcd']['byteorder'], '>')
            self.assertEqual(status['database_idx.tcd']['dirty'], 0)
            self.assertNotIn('indexed_tracks', status['database_partial.tcd'])
            self.assertNotIn('indexed_tracks', status['database_bad.tcd'])
            self.assertEqual(status['database_partial.tcd']['header_hex'], b'\x10\x48\x43\x54short'.hex())

    def test_completed_staging_file_is_restarted_before_master_commit_is_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / '.rockbox').mkdir()
            results = root / 'results'
            results.mkdir()

            class FakeSimulator:
                # Model only this documented external lifecycle: staged tags
                # exist before reboot; a committed master can exist after it.
                def __init__(self):
                    self.root, self.results = root, results
                    self.launches = self.stops = 0

                def launch(self):
                    self.launches += 1
                    if self.launches == 1:
                        (root / '.rockbox/database_tmp.tcd').write_bytes(struct.pack('<III', 0x54434810, 123, 2054))
                    else:
                        (root / '.rockbox/database_idx.tcd').write_bytes(struct.pack('<IIIIII', 0x54434810, 456, 2054, 0, 1, 0))

                def stop(self):
                    self.stops += 1

                def alive(self):
                    pass

                def expect(self, *args, **kwargs):
                    pass

                def capture(self, *args):
                    pass

                def key(self, *args):
                    pass

            sim = FakeSimulator()
            # No real simulator, subprocess, display, wait, or audio file.
            with patch('simulator_library_smoke.time.sleep'):
                initialize(sim, 2054)
            self.assertEqual((sim.launches, sim.stops), (2, 1))
            header = json.loads((results / 'database-header.json').read_text())
            self.assertEqual(header['indexed_tracks'], 2054)
            self.assertEqual(header['dirty'], 0)
            history = json.loads((results / 'database-initialization.json').read_text())['history']
            self.assertIn('before-required-restart', [entry['phase'] for entry in history])


if __name__ == '__main__':
    unittest.main()
