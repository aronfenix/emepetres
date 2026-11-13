"""Portable checks for the disposable FLAC fixture; no audio tools required."""
import struct
import unittest

from library_fixture import library_tracks, replace_comments, split_flac


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


if __name__ == '__main__':
    unittest.main()
