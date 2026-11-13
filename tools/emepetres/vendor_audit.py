#!/usr/bin/env python3
"""Read vendor/build bytes on a disposable Linux runner. Never run target code.

Only the report directory is suitable for uploading. Work files contain the
proprietary vendor image/rootfs and must remain on the disposable runner.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile

VENDOR_SHA256 = 'd56d5b093477ad32ad50d41f09155d23c9f9a458993d2e40e800dd704c73b8e6'
VENDOR_BYTES = 32466944
BUILD_REVISION = '9b56f100abb7c824668ca3fb8a35332d290d1dfe'
BUILD_RUN = '43276572060'
VENDOR_LOADER_SHA256 = '50344a0b3b3d817b485e32b79b671c217347ac532952724ee17413321db90ae8'
GLIBC_216_SOURCES = [
    'https://github.com/bminor/glibc/blob/glibc-2.16/elf/dl-version.c#L86-L99',
    'https://github.com/bminor/glibc/blob/glibc-2.16/elf/dl-lookup.c#L140-L167',
]


def parse_readelf(text):
    """Parse GNU readelf output in the C locale, including individual symbols."""
    if "Symbol table '.dynsym' contains" not in text:
        raise ValueError('Missing dynamic symbol table; imports cannot be verified')
    def field(label):
        match = re.search(r'^\s*' + re.escape(label) + r':\s*(.+)$', text, re.M)
        if not match:
            raise ValueError('Missing readelf field: ' + label)
        return match.group(1).strip()
    result = dict(class_=field('Class'), data=field('Data'), machine=field('Machine'),
                  flags=int(field('Flags').split(',')[0], 16),
                  flags_text=field('Flags'), needed=[], requires={},
                  definitions=[], exports=[], defaults=[], imports=[])
    result['class'] = result.pop('class_')
    interpreter = re.search(r'\[Requesting program interpreter:\s*([^\]]+)\]', text)
    result['interpreter'] = interpreter.group(1) if interpreter else None
    fp = re.search(r'^\s*FP ABI:\s*(.+)$', text, re.M)
    result['fp_abi'] = fp.group(1) if fp else None
    soname = re.search(r'\(SONAME\).*\[([^\]]+)\]', text)
    result['soname'] = soname.group(1) if soname else None
    result['needed'] = re.findall(r'\(NEEDED\).*\[([^\]]+)\]', text)
    result['search_paths'] = re.findall(r'\((?:RPATH|RUNPATH)\).*\[([^\]]*)\]', text)
    section, library = None, None
    version_owners, version_hidden, exported_indices, global_indices = {}, {}, {}, set()
    result['has_versym'] = bool(re.search(r'\(VERSYM\)', text))
    result['has_verdef'] = bool(re.search(r'\(VERDEF\)', text))
    for line in text.splitlines():
        if line.startswith('Symbol table '):
            section = 'symbols' if "'.dynsym'" in line else None
        elif line.startswith('Version needs section '):
            section = 'needs'
        elif line.startswith('Version definition section '):
            section = 'definitions'
        elif line.startswith('Version symbols section '):
            section = 'versyms'
            result['has_versym'] = True
        if section == 'symbols':
            match = re.match(r'\s*\d+:\s+\S+\s+\d+\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)', line)
            if not match:
                continue
            binding, visibility, index, decorated = match.groups()
            if binding not in ('GLOBAL', 'WEAK', 'UNIQUE'):
                continue
            parts = re.split(r'@{1,2}', decorated, maxsplit=1)
            name, version = parts[0], parts[1] if len(parts) > 1 else None
            if index == 'UND':
                number = re.search(r'\s+\((\d+)\)\s*$', line)
                result['imports'].append(dict(name=name, version=version, weak=binding == 'WEAK',
                    version_index=int(number.group(1)) if number else None))
            elif visibility in ('DEFAULT', 'PROTECTED'):
                result['exports'].append([name, version])
                index_match = re.match(r'\s*(\d+):', line)
                exported_indices[int(index_match.group(1))] = (name, version)
                if '@@' in decorated or version is None:
                    result['defaults'].append(name)
        elif section == 'needs':
            match = re.search(r'\bFile:\s*(\S+)', line)
            if match:
                library = match.group(1)
                result['requires'].setdefault(library, [])
            match = re.search(r'\bName:\s*(\S+)', line)
            if match and library:
                result['requires'][library].append(match.group(1))
                number = re.search(r'\bVersion:\s*(\d+)', line)
                if number:
                    raw_index = int(number.group(1))
                    version_owners[raw_index & 0x7fff] = library
                    version_hidden[raw_index & 0x7fff] = bool(raw_index & 0x8000)
        elif section == 'definitions':
            match = re.search(r'\bName:\s*(\S+)', line)
            if match:
                result['definitions'].append(match.group(1))
                result['has_verdef'] = True
        elif section == 'versyms':
            row = re.match(r'\s*([0-9a-f]+):\s*(.*)', line)
            if row:
                start = int(row.group(1), 16)
                cells = re.finditer(r'([0-9a-f]+)(h?)\s+\([^)]*\)', row.group(2))
                for offset, cell in enumerate(cells):
                    if int(cell.group(1), 16) == 1 and not cell.group(2):
                        global_indices.add(start + offset)
    for symbol in result['imports']:
        symbol['provider'] = version_owners.get(symbol['version_index'])
        symbol['version_hidden'] = version_hidden.get(symbol['version_index'])
    result['unversioned_globals'] = sorted({exported_indices[index][0] for index in global_indices
        if index in exported_indices and exported_indices[index][1] is None})
    return result


def compare_elf(consumer, providers, allow_glibc_216_fallback=False):
    """Check a consumer against its complete vendor dependency closure."""
    errors, weak, unresolved, fallbacks = [], [], [], []
    def unversioned_provider(provider):
        return (allow_glibc_216_fallback and provider.get('has_verdef') is False
                and provider.get('has_versym') is True)
    for name in consumer['needed']:
        if name not in providers:
            errors.append('Missing dependency: ' + name)
    for name, provider in providers.items():
        if any(consumer[key] != provider[key] for key in ('class', 'data', 'machine')):
            errors.append('ELF architecture mismatch: ' + name)
        # Compare o32/n32/64 ABI fields; PIC/CPIC/noreorder are not ABI conflicts.
        if (consumer['flags'] & 0xf060) != (provider['flags'] & 0xf060):
            errors.append('MIPS ABI flags mismatch: ' + name)
        if (consumer['flags'] & 0x400) != (provider['flags'] & 0x400):
            errors.append('MIPS NaN encoding mismatch: ' + name)
        if (consumer['flags'] & 0x0f000000) != (provider['flags'] & 0x0f000000):
            errors.append('MIPS architecture extension flags differ (requires review): ' + name)
        if (consumer['flags'] & 0xf0000000) != (provider['flags'] & 0xf0000000):
            errors.append('MIPS ISA flags differ (requires review): ' + name)
        if consumer.get('fp_abi') and provider.get('fp_abi') and consumer['fp_abi'] != provider['fp_abi']:
            errors.append('MIPS floating-point ABI differs (requires review): ' + name)
    for name, versions in consumer['requires'].items():
        provider = providers.get(name)
        if not provider:
            errors.append('Missing version provider: ' + name)
        else:
            for version in versions:
                if version not in provider['definitions']:
                    if unversioned_provider(provider):
                        unresolved.append('No provider version namespace: ' + name + ':' + version +
                                          '; glibc 2.16 may use global unversioned symbols (source inference, not executed)')
                    else:
                        errors.append('Missing version namespace: ' + name + ':' + version)
    for symbol in consumer['imports']:
        name, version = symbol['name'], symbol['version']
        candidates = list(providers.values())
        if version:
            # Verneed maps a namespace to its actual dependency. Do not accept
            # an identically named namespace exported by an unrelated library.
            if symbol.get('provider'):
                owners = [symbol['provider']]
            else:
                owners = [lib for lib, versions in consumer['requires'].items() if version in versions]
                if len(owners) != 1:
                    owners = []  # An ambiguous version namespace is insufficient evidence.
            candidates = [providers[lib] for lib in owners if lib in providers]
        found = any(([name, version] in item['exports'] if version else name in item['defaults'])
                    for item in candidates)
        if not found and version and symbol.get('version_hidden') is False:
            for owner in owners:
                provider = providers.get(owner)
                if (provider and unversioned_provider(provider)
                        and name in provider.get('unversioned_globals', [])
                        and [name, None] in provider['exports']):
                    fallbacks.append(dict(name=name, required_version=version, provider=owner,
                                          provider_version_index=1))
                    found = True
                    break
        if not found:
            decorated = name + ('@' + version if version else '')
            if symbol['weak']:
                weak.append(decorated)
            else:
                errors.append('Missing required symbol: ' + decorated)
    return dict(errors=sorted(set(errors)), unresolved_weak=sorted(set(weak)),
                unresolved=sorted(set(unresolved)), unversioned_fallbacks=fallbacks)


def vendor_path(root, path):
    """Resolve vendor absolute symlinks in the virtual root, never host /lib."""
    parts, pending = [], list(PurePosixPath(str(path)).parts)
    links = 0
    while pending:
        part = pending.pop(0)
        if part in ('/', '//', '.'):
            continue
        if part == '..':
            if not parts:
                raise ValueError('Vendor path escapes virtual root')
            parts.pop()
            continue
        candidate = root.joinpath(*parts, part)
        if candidate.is_symlink():
            links += 1
            if links > 40:
                raise ValueError('Vendor symlink loop')
            target = PurePosixPath(os.readlink(candidate))
            if target.is_absolute():
                parts = []
            pending = list(target.parts) + pending
        else:
            parts.append(part)
    return root.joinpath(*parts)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_iso(source, destination):
    """Read the fixed, hash-pinned ISO9660 image without mounting it."""
    data = source.read_bytes()
    if len(data) != VENDOR_BYTES or hashlib.sha256(data).hexdigest() != VENDOR_SHA256:
        raise ValueError('Vendor image size/SHA-256 mismatch')
    sector = 2048
    pvd = data[16 * sector:17 * sector]
    if pvd[:7] != b'\x01CD001\x01' or int.from_bytes(pvd[128:130], 'little') != sector:
        raise ValueError('Expected ISO9660 primary descriptor')
    record = pvd[156:190]
    offset, size = int.from_bytes(record[2:6], 'little') * sector, int.from_bytes(record[10:14], 'little')
    directory = data[offset:offset + size]
    position, payloads, records = 0, {}, []
    destination.mkdir(parents=True)
    while position < len(directory):
        length = directory[position]
        if not length:
            position = (position // sector + 1) * sector
            continue
        record = directory[position:position + length]
        if len(record) != length or length < 34:
            raise ValueError('Invalid ISO directory record')
        raw_name = record[33:33 + record[32]]
        position += length
        if raw_name in (b'\x00', b'\x01'):
            continue
        name = raw_name.decode('ascii').split(';')[0].lower()
        if record[25] & 2 or '/' in name or '\\' in name or name in ('.', '..'):
            raise ValueError('Unexpected ISO path')
        offset = int.from_bytes(record[2:6], 'little') * sector
        size = int.from_bytes(record[10:14], 'little')
        content = data[offset:offset + size]
        if len(content) != size:
            raise ValueError('Truncated ISO payload')
        payloads[name] = content
        records.append(dict(name=name, bytes=size, sha256=hashlib.sha256(content).hexdigest()))
        (destination / name).write_bytes(content)
    manifest = payloads['update.txt'].decode('ascii')
    checks = re.findall(r'file_path=autoupdate/(\S+)\s+md5=([a-f0-9]{32})', manifest)
    if len(checks) != 3 or not all(hashlib.md5(payloads[name]).hexdigest() == digest for name, digest in checks):
        raise ValueError('Vendor internal payload MD5 mismatch')
    return dict(bytes=len(data), sha256=VENDOR_SHA256, payloads=records,
                internal_md5_checks='3/3 match',
                version=payloads['version.txt'].decode('ascii').strip('\x00\r\n'))


def readelf(path, logs, label):
    env = dict(os.environ, LC_ALL='C')
    result = subprocess.run(['readelf', '-hW', '-lW', '-dW', '--dyn-syms', '-VW', '-A', str(path)],
                            text=True, capture_output=True, env=env, check=False)
    (logs / (label + '.readelf.txt')).write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode or result.stderr.strip():
        raise ValueError('readelf failed or reported diagnostics: ' + label)
    info = parse_readelf(result.stdout)
    info.update(sha256=sha256(path), bytes=path.stat().st_size)
    if info['class'] != 'ELF32' or 'little endian' not in info['data'] or 'MIPS' not in info['machine']:
        raise ValueError('Expected ELF32 little-endian MIPS: ' + label)
    return info


def build_inputs(directory, work):
    candidates = list(directory.rglob('source-revision.txt'))
    if len(candidates) != 1:
        raise ValueError('Expected exactly one build artifact source-revision.txt')
    root = candidates[0].parent
    if candidates[0].read_text().strip() != BUILD_REVISION:
        raise ValueError('Build source revision mismatch')
    checks = []
    for line in (root / 'target-sha256.txt').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.removeprefix('*')
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or sha256(path) != digest:
            raise ValueError('Artifact checksum/path mismatch: ' + name)
        checks.append(dict(path=name, sha256=digest, bytes=path.stat().st_size))
    expected = {'build-agptekrocker-n/rockbox.rocker', 'build-agptekrocker-b/bootloader.rocker',
                'build-agptekrocker-n/rockbox.zip'}
    if not expected.issubset({entry['path'] for entry in checks}):
        raise ValueError('Artifact manifest omits required hosted outputs')
    core = root / 'build-agptekrocker-n/rockbox.rocker'
    plugin = work / 'lastfm_scrobbler.rock'
    with zipfile.ZipFile(root / 'build-agptekrocker-n/rockbox.zip') as package:
        if package.read('.rockbox/rockbox.rocker') != core.read_bytes():
            raise ValueError('Packaged application differs from standalone output')
        plugin.write_bytes(package.read('.rockbox/rocks/apps/lastfm_scrobbler.rock'))
    return dict(application=core, bootloader=root / 'build-agptekrocker-b/bootloader.rocker',
                lastfm_plugin=plugin), dict(run=BUILD_RUN, revision=BUILD_REVISION,
                compiler=(root / 'compiler-version.txt').read_text().strip(), checks=checks)


def rootfs_files(root):
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if not (Path(directory) / name).is_symlink())
        for name in sorted(files):
            yield Path(directory) / name


def script_evidence(root):
    """Upload line excerpts/metadata, never the extracted scripts themselves."""
    expression = re.compile(r'mount|mmcblk|exfat|hiby_player|recover|autoupdate|update\.upt|mtd|flash', re.I)
    scripts, hits = [], []
    categories = dict(mount=[], startup=[], recovery=[])
    for path in rootfs_files(root):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not (relative.startswith('etc/') or relative.endswith('.sh')):
            continue
        content = path.read_bytes()
        if len(content) > 512 * 1024 or b'\x00' in content:
            continue
        text = content.decode('utf-8', errors='replace')
        relevant = []
        for number, line in enumerate(text.splitlines(), 1):
            if expression.search(line):
                relevant.append(dict(line=number, text=line[:500]))
        if relevant:
            scripts.append(dict(path='/' + relative, sha256=hash256(content), bytes=len(content)))
            hits.extend(dict(path='/' + relative, **line) for line in relevant)
            if any(re.search(r'mount|mmcblk|exfat', item['text'], re.I) for item in relevant):
                categories['mount'].append('/' + relative)
            if relative.startswith(('etc/init.d/', 'etc/rc')) or relative == 'etc/inittab' or 'hiby_player' in text:
                categories['startup'].append('/' + relative)
            if any(re.search(r'recover|autoupdate|update\.upt|mtd|flash', item['text'], re.I) for item in relevant):
                categories['recovery'].append('/' + relative)
    return dict(scripts=scripts, excerpts=hits, categories=categories)


def hash256(content):
    return hashlib.sha256(content).hexdigest()


def extraction_errors(output):
    # The extractor can emit Warn and still exit zero after losing file bytes.
    # Missing privileged device nodes are harmless for a read-only ELF audit.
    return bool(re.search(r'\b(?:Error|Fatal|Traceback)\b|Data may be missing|bad blocks|'
                          r'Path traversal attempt|\b(?:DIR|FILE|SYMLINK) Fail', output, re.I))


def audit(args, report):
    work = args.work_dir.resolve()
    if work.exists() and any(work.iterdir()):
        raise ValueError('Work directory must be empty disposable storage')
    work.mkdir(parents=True, exist_ok=True)
    report['vendor'] = extract_iso(args.vendor_image, work / 'iso')
    with (work / 'iso/system.ubi').open('rb') as rootfs_image:
        magic = rootfs_image.read(4)
    report['vendor']['rootfs_magic_hex'] = magic.hex()
    report['vendor']['rootfs_container'] = ('raw UBIFS' if magic == b'\x31\x18\x10\x06' else
                                          'UBI' if magic == b'UBI!' else 'extractor autodetection required')
    from importlib.metadata import version
    if version('ubi-reader') != '0.8.16':
        raise ValueError('Required runner extractor: ubi-reader==0.8.16')
    report['extractor'] = 'ubi-reader==0.8.16'
    extraction = subprocess.run(['ubireader_extract_files', '-o', str(work / 'rootfs'),
                                str(work / 'iso/system.ubi')], text=True, capture_output=True, check=False)
    (args.report_dir / 'rootfs-extraction.log').write_text(extraction.stdout + extraction.stderr, encoding='utf-8')
    if extraction.returncode or extraction_errors(extraction.stdout + extraction.stderr):
        raise ValueError('UBIFS extraction failed or reported errors; inspect extraction log')
    # UBI volumes introduce extra path components; a raw UBIFS image does not.
    roots = [path.parent for path in (work / 'rootfs').rglob('lib')
             if path.is_dir() and not path.is_symlink() and (path.parent / 'etc').is_dir()]
    if len(roots) != 1:
        raise ValueError('Expected exactly one extracted rootfs with lib and etc')
    root = roots[0]
    report['stock_scripts'] = script_evidence(root)
    for category, paths in report['stock_scripts']['categories'].items():
        if not paths:
            report['unresolved'].append('No stock ' + category + ' script evidence found in inspected text files')
    inputs, report['build'] = build_inputs(args.build_dir, work)
    report['targets'], report['libraries'] = {}, {}
    aliases = {}
    for path in rootfs_files(root):
        if path.name.endswith('.so') or '.so.' in path.name:
            aliases.setdefault(path.name, []).append('/' + path.relative_to(root).as_posix())
    cache = {}
    def library(name):
        candidates = aliases.get(name, [])
        # Model the normal dynamic loader's built-in directories. A dependency
        # elsewhere requires actual loader configuration and must be reviewed.
        standard = [item for item in candidates if str(PurePosixPath(item).parent) in ('/lib', '/usr/lib')]
        if not standard:
            raise ValueError('Dependency absent from /lib or /usr/lib: ' + name)
        chosen = '/lib/' + name if '/lib/' + name in standard else standard[0]
        path = vendor_path(root, chosen)
        if not path.is_file():
            raise ValueError('Broken vendor library link: ' + chosen)
        if path not in cache:
            cache[path] = readelf(path, args.report_dir, 'vendor-' + path.name)
        value = cache[path]
        if value['soname'] and value['soname'] != name:
            raise ValueError('Requested dependency/SONAME mismatch: ' + name + '/' + value['soname'])
        report['libraries'][name] = dict(path=chosen, resolved='/' + path.relative_to(root).as_posix(), **value)
        return value
    for label, path in inputs.items():
        consumer = readelf(path, args.report_dir, label)
        if not consumer['fp_abi']:
            report['unresolved'].append(label + ': no readelf MIPS FP ABI attribute')
        providers, pending = {}, list(consumer['needed'])
        while pending:
            name = pending.pop(0)
            if name in providers:
                continue
            try:
                providers[name] = library(name)
            except ValueError as error:
                report['errors'].append(label + ': ' + str(error))
                continue
            pending.extend(item for item in providers[name]['needed'] if item not in providers)
        if label != 'lastfm_plugin' and consumer['interpreter'] != '/lib/ld.so.1':
            report['errors'].append(label + ': unexpected or missing ELF interpreter')
        # A dlopened plugin inherits the application's loader even though it
        # has no PT_INTERP. Include its exports for libc's private imports too.
        loader_name = consumer['interpreter'] or '/lib/ld.so.1'
        loader_path = vendor_path(root, loader_name)
        allow_fallback = False
        if not loader_path.is_file():
            report['errors'].append(label + ': missing vendor ELF interpreter')
        else:
            loader = readelf(loader_path, args.report_dir, 'vendor-loader')
            report['loader'] = dict(path=loader_name, **loader)
            providers.setdefault('ld.so.1', loader)
            allow_fallback = loader['sha256'] == VENDOR_LOADER_SHA256
            report['loader_semantics'] = dict(model='glibc-2.16-source-inference',
                enabled_for_known_loader=allow_fallback, known_loader_sha256=VENDOR_LOADER_SHA256,
                primary_sources=GLIBC_216_SOURCES,
                limitation='Vendor loader execution and source/binary equivalence have not been verified.')
        comparison = compare_elf(consumer, providers, allow_glibc_216_fallback=allow_fallback)
        report['errors'].extend(label + ': ' + error for error in comparison['errors'])
        report['unresolved'].extend(label + ': ' + item for item in comparison['unresolved'])
        if comparison['unversioned_fallbacks']:
            report['unresolved'].append(label + ': ' + str(len(comparison['unversioned_fallbacks'])) +
                ' imports rely on inferred glibc 2.16 unversioned fallback; vendor loader/audio not executed')
        closure = {}
        for name, provider in providers.items():
            if not provider['fp_abi']:
                report['unresolved'].append(name + ': no readelf MIPS FP ABI attribute')
            if provider['search_paths']:
                report['unresolved'].append(name + ': runtime RPATH/RUNPATH present: ' + repr(provider['search_paths']))
            checked = compare_elf(provider, providers, allow_glibc_216_fallback=allow_fallback)
            closure[name] = checked
            report['errors'].extend(label + ' dependency ' + name + ': ' + error for error in checked['errors'])
            report['unresolved'].extend(label + ' dependency ' + name + ': ' + item for item in checked['unresolved'])
        report['targets'][label] = dict(elf=consumer, comparison=comparison,
                                       dependency_closure=closure)
        if consumer['search_paths']:
            report['unresolved'].append(label + ': runtime RPATH/RUNPATH present: ' + repr(consumer['search_paths']))
    report['limitations'] = [
        'Static byte inspection only; no vendor or MIPS executable was run.',
        'Stock 1.1 bytes are not proof of the physical player revision/current firmware.',
        'No installation, SD mount, audio, Last.fm export, recovery or rollback was exercised.',
        'Different ISA/FP flags fail conservatively for review. Missing FP attributes cannot prove the calling convention.',
        'Library lookup models /lib then /usr/lib; runtime loader configuration and symbol interposition remain untested.',
        'Weak unresolved symbols are recorded but do not fail ELF linking compatibility.',
        'ubi-reader does not replay the UBIFS journal; uncommitted entries may be absent.',
        'Source-inferred glibc fallback is conditional; matching unversioned symbol names does not prove function ABI/audio behavior.',
        'A passing report is not an installation kit or permission to flash/format storage.',
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-image', required=True, type=Path)
    parser.add_argument('--build-dir', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--report-dir', required=True, type=Path)
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report = dict(status='FAILED', errors=[], unresolved=[], build_run=BUILD_RUN, expected_revision=BUILD_REVISION)
    try:
        audit(args, report)
    except Exception as error:
        report['errors'].append(type(error).__name__ + ': ' + str(error))
    report['errors'] = sorted(set(report['errors']))
    report['unresolved'] = sorted(set(report['unresolved']))
    report['status'] = ('FAILED' if report['errors'] else
        'STATIC_AUDIT_CONDITIONAL_UNVERIFIED_ON_HARDWARE' if report['unresolved'] else
        'STATIC_AUDIT_PASSED_UNVERIFIED_ON_HARDWARE')
    (args.report_dir / 'vendor-audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    lines = ['# Vendor static ABI audit', '', 'Status: ' + report['status'], '',
             'Build run: ' + BUILD_RUN, 'Build source: `' + BUILD_REVISION + '`',
             'Vendor SHA-256: `' + VENDOR_SHA256 + '`', '',
             '## Errors', '']
    lines += ['- ' + item for item in report['errors']] or ['None.']
    lines += ['', '## Targets', '', '| Target | Bytes | Imports | Vendor dependencies | Conditional fallbacks | Errors |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    for label, entry in report.get('targets', {}).items():
        elf = entry['elf']
        lines.append('| ' + label + ' | ' + str(elf['bytes']) + ' | ' + str(len(elf['imports'])) +
                     ' | ' + str(len(entry['dependency_closure'])) + ' | ' +
                     str(len(entry['comparison']['unversioned_fallbacks'])) + ' | ' +
                     str(len(entry['comparison']['errors'])) + ' |')
    lines += ['', '## Stock scripts', '']
    for category, paths in report.get('stock_scripts', {}).get('categories', {}).items():
        lines.append('- ' + category + ': ' + (', '.join('`' + path + '`' for path in paths) or 'not found'))
    lines += ['', 'Exact numbered excerpts, library symbols, dependency closures and checksums are in `vendor-audit.json`.',
              '', '## Unresolved static evidence', '']
    lines += ['- ' + item for item in report['unresolved']] or ['None recorded; physical verification is still required.']
    if any(entry['comparison']['unversioned_fallbacks'] for entry in report.get('targets', {}).values()):
        lines += ['', '## Conditional loader fallback', '',
            'Every fallback symbol, requested version and exact provider is listed in `vendor-audit.json`. '
            'No vendor code was executed. This is source-based inference for the hash-identified vendor loader, '
            'not proof of its runtime behavior or of function/audio ABI compatibility.', '',
            '| Target | Symbol | Requested version | Unversioned provider |', '| --- | --- | --- | --- |']
        for label, entry in report['targets'].items():
            for symbol in entry['comparison']['unversioned_fallbacks']:
                lines.append('| ' + label + ' | `' + symbol['name'] + '` | `' + symbol['required_version'] +
                             '` | `' + symbol['provider'] + '` (global index 1) |')
        lines += ['', 'Primary glibc 2.16 source:'] + ['- ' + url for url in GLIBC_216_SOURCES]
    lines += ['', '## Limitations', '']
    lines += ['- ' + item for item in report.get('limitations', ['Audit stopped before all checks completed.'])]
    (args.report_dir / 'vendor-audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(report['status'])
    for error in report['errors']:
        print(error)
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
