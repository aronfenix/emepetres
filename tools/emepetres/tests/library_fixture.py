"""Synthetic-only FLAC metadata fixtures (stdlib; no user library access).

FLAC block headers: RFC 9639 section 8.1; Vorbis comments: section 8.6.
https://www.rfc-editor.org/rfc/rfc9639.html#section-8.6
Only the comment block changes. STREAMINFO and compressed frames stay intact.
"""
import json
from pathlib import Path
import struct
import subprocess


def split_flac(raw):
    if raw[:4] != b'fLaC':
        raise ValueError('fixture seed is not native FLAC')
    blocks, offset = [], 4
    while True:
        if offset + 4 > len(raw):
            raise ValueError('truncated FLAC metadata header')
        flag = raw[offset]
        size = int.from_bytes(raw[offset + 1:offset + 4], 'big')
        offset += 4
        if offset + size > len(raw):
            raise ValueError('truncated FLAC metadata body')
        blocks.append((flag & 127, raw[offset:offset + size]))
        offset += size
        if flag & 128:
            break
    if blocks[0][0] != 0 or len(blocks[0][1]) != 34:
        raise ValueError('missing FLAC STREAMINFO')
    return blocks, raw[offset:]


def replace_comments(raw, tags):
    blocks, frames = split_flac(raw)
    vendor = b'emepetres synthetic fixture'
    comment = struct.pack('<I', len(vendor)) + vendor + struct.pack('<I', len(tags))
    for key, value in tags.items():
        value = f'{key}={value}'.encode('utf-8')
        comment += struct.pack('<I', len(value)) + value
    blocks = [(kind, data) for kind, data in blocks if kind != 4] + [(4, comment)]
    result = bytearray(b'fLaC')
    for index, (kind, data) in enumerate(blocks):
        if len(data) >= 1 << 24:
            raise ValueError('FLAC metadata block exceeds 24-bit size')
        result += bytes([kind | (128 if index == len(blocks) - 1 else 0)])
        result += len(data).to_bytes(3, 'big') + data
    return bytes(result) + frames


def library_tracks():
    # Reverse disc/track order and title order relative to filenames on purpose.
    for index, (disc, track, title) in enumerate([(2, 2, 'Four'), (2, 1, 'Three'),
                                                  (1, 2, 'Two'), (1, 1, 'One')]):
        yield f'edge/{index}.flac', dict(ARTIST='Aster', ALBUM='Delta', TITLE=title,
                                       DISCNUMBER=str(disc), TRACKNUMBER=str(track))
    yield 'edge/echo-aster.flac', dict(ARTIST='Aster', ALBUM='Echo', TITLE='Amber', TRACKNUMBER='1')
    yield 'edge/echo-zulu.flac', dict(ARTIST='Zulu', ALBUM='Echo', TITLE='Indigo', TRACKNUMBER='1')
    for artist in range(256):
        for track in range(1, 9):
            yield f'bison-{artist:03d}/{track:02d}.flac', dict(
                ARTIST=f'Bison {artist:03d}', ALBUM=f'Opus {artist:03d}',
                TITLE=f'Tune {track:03d}', TRACKNUMBER=str(track))


def create_library(root, report):
    """One encoder call for 2,054 valid FLACs; ffprobe/decode two edge files."""
    root, report = Path(root), Path(report)
    root.mkdir()
    seed = root / 'seed.flac'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'anullsrc=r=44100:cl=mono', '-t', '31', '-c:a', 'flac', str(seed)], check=True)
    raw = seed.read_bytes()
    manifest = []
    for relative, tags in library_tracks():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(replace_comments(raw, tags))
        manifest.append(dict(file=relative, tags=tags))
    seed.unlink()
    for relative in ('edge/0.flac', 'edge/echo-zulu.flac'):
        target = root / relative
        probe = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format_tags', '-of', 'json', str(target)], text=True))
        actual = {key.upper(): value for key, value in probe['format']['tags'].items()}
        # libavformat exposes standard Vorbis names through generic aliases.
        for vorbis, generic in (('TRACKNUMBER', 'TRACK'), ('DISCNUMBER', 'DISC')):
            if vorbis not in actual and generic in actual:
                actual[vorbis] = actual[generic]
        expected = next(item['tags'] for item in manifest if item['file'] == relative)
        assert all(actual.get(key) == value for key, value in expected.items()), (relative, actual, expected)
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(target), '-f', 'null', '-'], check=True)
    report.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return dict(tracks=len(manifest), artists=258, albums=258)
