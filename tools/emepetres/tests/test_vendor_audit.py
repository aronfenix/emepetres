"""Offline audit fixtures: no device, vendor download, tools or account required."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

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

    def test_missing_dynamic_symbol_table_cannot_pass_as_no_imports(self):
        with self.assertRaises(ValueError):
            audit.parse_readelf(HEADER.split('Symbol table')[0])

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

    def test_same_namespace_in_other_needed_library_cannot_supply_symbol(self):
        text = HEADER.replace('FP ABI:', '''  0x0020: Version: 1  File: libpthread.so.0  Cnt: 1
  0x0030:   Name: GLIBC_2.0  Flags: none  Version: 3
FP ABI:''')
        self.consumer = audit.parse_readelf(text)
        self.providers['libpthread.so.0'] = self.provider.copy()
        self.provider['exports'] = []
        self.assertIn('memcpy@GLIBC_2.0', '\n'.join(
            audit.compare_elf(self.consumer, self.providers)['errors']))

    def test_mips_nan_encoding_mismatch_fails(self):
        self.provider['flags'] ^= 0x400
        result = audit.compare_elf(self.consumer, self.providers)
        self.assertTrue(any('NaN' in item for item in result['errors']))

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
    def test_double_slash_absolute_path_stays_inside_vendor_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(audit.vendor_path(root, '//lib/libc.so.6'), root / 'lib/libc.so.6')

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


class ArtifactValidation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'download/emepetres/emepetres'
        self.root.mkdir(parents=True)
        self.work = self.directory / 'work'
        self.work.mkdir()
        (self.root / 'source-revision.txt').write_text(audit.BUILD_REVISION + '\n')
        (self.root / 'compiler-version.txt').write_text('fixture GCC 9.5.0\n')
        for name in ('build-agptekrocker-n', 'build-agptekrocker-b'):
            (self.root / name).mkdir()
        self.core = self.root / 'build-agptekrocker-n/rockbox.rocker'
        self.core.write_bytes(b'fixture application')
        self.boot = self.root / 'build-agptekrocker-b/bootloader.rocker'
        self.boot.write_bytes(b'fixture bootloader')
        self.package = self.root / 'build-agptekrocker-n/rockbox.zip'
        self.write_package(self.core.read_bytes())

    def write_package(self, core):
        with zipfile.ZipFile(self.package, 'w') as package:
            package.writestr('.rockbox/rockbox.rocker', core)
            package.writestr('.rockbox/rocks/apps/lastfm_scrobbler.rock', b'fixture plugin')
        self.write_manifest()

    def write_manifest(self):
        lines = [audit.sha256(path) + '  ' + path.relative_to(self.root).as_posix()
                 for path in (self.core, self.boot, self.package)]
        (self.root / 'target-sha256.txt').write_text('\n'.join(lines) + '\n')

    def test_finds_nested_cross_run_common_root_and_checks_packaged_core(self):
        inputs, metadata = audit.build_inputs(self.directory / 'download', self.work)
        self.assertEqual(inputs['application'], self.core)
        self.assertEqual(inputs['lastfm_plugin'].read_bytes(), b'fixture plugin')
        self.assertEqual(metadata['revision'], audit.BUILD_REVISION)
        self.assertEqual(len(metadata['checks']), 3)

    def test_mismatched_revision_and_payload_fail(self):
        (self.root / 'source-revision.txt').write_text('wrong revision')
        with self.assertRaisesRegex(ValueError, 'revision mismatch'):
            audit.build_inputs(self.directory / 'download', self.work)
        (self.root / 'source-revision.txt').write_text(audit.BUILD_REVISION)
        self.core.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum/path mismatch'):
            audit.build_inputs(self.directory / 'download', self.work)

    def test_packaged_core_mismatch_is_rejected_even_with_valid_manifest(self):
        self.write_package(b'wrong core')
        with self.assertRaisesRegex(ValueError, 'Packaged application differs'):
            audit.build_inputs(self.directory / 'download', self.work)

    def test_manifest_omission_cannot_bypass_output_hash_checks(self):
        (self.root / 'target-sha256.txt').write_text('')
        with self.assertRaisesRegex(ValueError, 'omits required'):
            audit.build_inputs(self.directory / 'download', self.work)

    def test_manifest_cannot_reference_outside_artifact_root(self):
        outside = self.directory / 'outside'
        outside.write_bytes(b'outside fixture')
        (self.root / 'target-sha256.txt').write_text(audit.sha256(outside) + '  ' + str(outside))
        with self.assertRaisesRegex(ValueError, 'checksum/path mismatch'):
            audit.build_inputs(self.directory / 'download', self.work)


class ScriptEvidence(unittest.TestCase):
    def test_reports_numbered_mount_lines_without_copying_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'etc/init.d').mkdir(parents=True)
            (root / 'etc/init.d/rcS').write_text('#!/bin/sh\nmount /dev/mmcblk0p1 /mnt/sd\n')
            (root / 'etc/unrelated').write_text('no evidence\n')
            result = audit.script_evidence(root)
            self.assertEqual(result['scripts'][0]['path'], '/etc/init.d/rcS')
            self.assertEqual(result['excerpts'], [dict(path='/etc/init.d/rcS', line=2,
                                  text='mount /dev/mmcblk0p1 /mnt/sd')])


class ExtractionDiagnostics(unittest.TestCase):
    def test_content_loss_warning_fails_even_if_extractor_exits_zero(self):
        for message in ('Warn: Data may be missing or corrupted, bad blocks',
                        'Warn: FILE Fail: permission denied',
                        'Warn: SYMLINK Fail: broken',
                        'Warn: Path traversal attempt: ../../outside, discarding.',
                        'Error: decompression failed', 'Traceback (most recent call last):'):
            with self.subTest(message=message):
                self.assertTrue(audit.extraction_errors(message))

    def test_unprivileged_device_node_skip_does_not_impair_library_audit(self):
        self.assertFalse(audit.extraction_errors('Warn: DEV Fail: Operation not permitted'))


if __name__ == '__main__':
    unittest.main()
