"""Fast OCR calibration on exact CI screenshots; no simulator/display needed."""
from pathlib import Path
import shutil
import unittest

from simulator_library_smoke import read_selected, selected_matches


FIXTURES = Path(__file__).with_name('ocr_fixtures')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('tesseract'),
                     'runner ffmpeg and tesseract required')
class LibraryOCR(unittest.TestCase):
    def test_exact_selected_labels_and_rejects_wrong_visible_rows(self):
        for filename, expected in [('albums.png', 'Albums'), ('artists.png', 'Artists'),
                                   ('bison-cf.png', 'Bison CF'), ('tune-one.png', 'Tune One')]:
            with self.subTest(filename=filename):
                state = read_selected(FIXTURES / filename, expected)
                self.assertTrue(state['cursor'], state)
                variants = state['selected_variants']
                self.assertTrue(any(selected_matches(expected, item['text']) for item in variants), state)
                for wrong in ('Artist', 'Artists', 'Albums', 'Bison CF', 'Tune One',
                              'Random', 'Zulu', 'Indigo', 'Search'):
                    if wrong == expected:
                        continue
                    self.assertFalse(any(selected_matches(wrong, item['text']) for item in variants),
                                     (wrong, state))
                if expected == 'Albums':
                    self.assertEqual(variants[0]['name'], 'threshold8-psm7')
                    if not selected_matches(expected, variants[0]['text']):
                        self.assertGreater(len(variants), 1, 'mismatched primary must try alternatives')


if __name__ == '__main__':
    unittest.main()
