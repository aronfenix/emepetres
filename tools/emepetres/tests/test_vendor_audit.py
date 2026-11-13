"""Offline audit fixtures: no device, vendor download, tools or account required."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    'vendor_audit', Path(__file__).parents[1] / 'vendor_audit.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

HEADER = '''
  Class:                             ELF32
  Data:                              2's complement, little endian
  Machine:                           MIPS R3000
  Flags:                             0x70001007, noreorder, pic, cpic, o32, mips32r2
      [Requesting program interpreter: /lib/ld.so.1]
 0x00000001 (NEEDED)                     Shared library: [libc.so.6]
 0x0000000e (SONAME)                     Library soname: [libsample.so.1]
Symbol table '.dynsym' contains 4 entries:
   Num:    Value  Size Type    Bind   Vis      Ndx Name
     1: 00000000     0 FUNC    GLOBAL DEFAULT  UND memcpy@GLIBC_2.0 (2)
     2: 00000000     0 NOTYPE  WEAK   DEFAULT  UND optional
     3: 00001000    24 FUNC    GLOBAL DEFAULT   12 answer@@SAMPLE_1.0
Version needs section '.gnu.version_r' contains 1 entry:
  000000: Version: 1  File: libc.so.6  Cnt: 1
  0x0010:   Name: GLIBC_2.0  Flags: none  Version: 2
FP ABI: Hard float (double precision)
'''


def info(symbols='', needs='', definitions=''):
    text = HEADER.split("Symbol table")[0] + "Symbol table '.dynsym' contains 9 entries:\n" + symbols
    text += "\nVersion definition section '.gnu.version_d' contains 2 entries:\n" + definitions
    text += "\nVersion needs section '.gnu.version_r' contains 1 entry:\n" + needs
    return audit.parse_readelf(text)


class ReadelfParser(unittest.TestCase):
    def test_parses_real_style_versioned_imports_exports_and_weak(self):
        result = audit.parse_readelf(HEADER)
        self.assertEqual(result['interpreter'], '/lib/ld.so.1')
        self.assertEqual(result['needed'], ['libc.so.6'])
        self.assertEqual(result['soname'], 'libsample.so.1')
        self.assertEqual(result['flags'], 0x70001007)
        self.assertEqual(result['requires']['libc.so.6'], ['GLIBC_2.0'])
        self.assertEqual(result['imports'][0]['name'], 'memcpy')
        self.assertEqual(result['imports'][0]['version'], 'GLIBC_2.0')
        self.assertTrue(result['imports'][1]['weak'])
        self.assertIn(['answer', 'SAMPLE_1.0'], result['exports'])

    def test_rejects_truncated_or_non_elf_output(self):
        with self.assertRaises(ValueError):
            audit.parse_readelf('readelf: Error: not an ELF file')

    def test_exports_exclude_hidden_and_local_symbols(self):
        result = info('''
  1: 00001000 24 FUNC LOCAL DEFAULT 12 local
  2: 00001000 24 FUNC GLOBAL HIDDEN 12 hidden
  3: 00001000 24 FUNC WEAK DEFAULT 12 visible
''')
        self.assertEqual(result['exports'], [['visible', None]])


class SymbolComparison(unittest.TestCase):
    def setUp(self):
        self.consumer = audit.parse_readelf(HEADER)
        self.provider = info('  1: 00001000 24 FUNC GLOBAL DEFAULT 12 memcpy@@GLIBC_2.0\n',
                             definitions='  0x001c: Rev: 1 Flags: none Index: 2 Cnt: 1 Name: GLIBC_2.0\n')
        self.providers = {'libc.so.6': self.provider}

    def test_exact_symbol_version_passes_with_unresolved_weak_recorded(self):
        result = audit.compare_elf(self.consumer, self.providers)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['unresolved_weak'], ['optional'])

    def test_version_namespace_alone_does_not_prove_symbol_available(self):
        self.provider['exports'] = [['memcpy', 'GLIBC_2.2']]
        result = audit.compare_elf(self.consumer, self.providers)
        self.assertIn('memcpy@GLIBC_2.0', '\n'.join(result['errors']))

    def test_matching_symbol_in_wrong_version_provider_does_not_pass(self):
        self.providers['libwrong.so.1'] = self.provider.copy()
        self.provider['exports'] = []
        result = audit.compare_elf(self.consumer, self.providers)
        self.assertIn('memcpy@GLIBC_2.0', '\n'.join(result['errors']))

    def test_missing_needed_library_fails_even_without_imports(self):
        self.consumer['imports'] = []
        result = audit.compare_elf(self.consumer, {})
        self.assertIn('Missing dependency: libc.so.6', result['errors'])

    def test_wrong_architecture_and_mips_abi_fail(self):
        self.provider['class'] = 'ELF64'
        self.provider['flags'] ^= 0x20
        result = audit.compare_elf(self.consumer, self.providers)
        self.assertTrue(any('architecture' in item for item in result['errors']))
        self.assertTrue(any('MIPS ABI' in item for item in result['errors']))

    def test_unversioned_import_accepts_only_default_symbol_version(self):
        self.consumer['imports'] = [{'name': 'memcpy', 'version': None, 'weak': False}]
        self.provider['exports'] = [['memcpy', 'GLIBC_2.0']]
        self.provider['defaults'] = []
        self.assertTrue(audit.compare_elf(self.consumer, self.providers)['errors'])
        self.provider['defaults'] = ['memcpy']
        self.assertEqual(audit.compare_elf(self.consumer, self.providers)['errors'], [])


class RootfsPaths(unittest.TestCase):
    def test_absolute_vendor_symlink_is_resolved_inside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'lib').mkdir()
            target = root / 'lib/libc-2.19.so'
            target.write_bytes(b'vendor fixture')
            try:
                (root / 'lib/libc.so.6').symlink_to('/lib/libc-2.19.so')
            except OSError:
                self.skipTest('symlinks unavailable on this host')
            self.assertEqual(audit.vendor_path(root, '/lib/libc.so.6'), target)

    def test_parent_traversal_and_symlink_loops_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                audit.vendor_path(root, '../../outside')
            try:
                (root / 'loop').symlink_to('loop')
            except OSError:
                self.skipTest('symlinks unavailable on this host')
            with self.assertRaises(ValueError):
                audit.vendor_path(root, 'loop')


if __name__ == '__main__':
    unittest.main()
