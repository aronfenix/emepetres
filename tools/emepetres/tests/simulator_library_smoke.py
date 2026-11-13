#!/usr/bin/env python3
"""Assert real Rocker SDL library states under Xvfb, using synthetic audio only.

Run from repository root: xvfb-run -a python3 tools/emepetres/tests/simulator_library_smoke.py BUILD
Runner dependencies: ffmpeg/ffprobe, xdotool, tesseract-ocr (English). No pip packages.
Never operates on a real player, real music, a desktop session, or Last.fm.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
import zipfile

from library_fixture import create_library


def run(args, **kwargs):
    return subprocess.run(args, check=True, timeout=30, **kwargs)


def normalized(text):
    return ' '.join(text.casefold().split())


def selected_matches(expected, observed):
    return re.search(r'(?<!\w)' + re.escape(normalized(expected)) + r'(?!\w)',
                     normalized(observed)) is not None


def ocr_image(png, filters, mode):
    enlarged = run(['ffmpeg', '-v', 'error', '-i', str(png), '-vf', filters,
                    '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-'],
                   capture_output=True).stdout
    return run(['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', str(mode)],
               input=enlarged, capture_output=True).stdout.decode('utf-8')


def read_selected(png, expected=None):
    """OCR the actual cursor row; bounded alternatives only on exact mismatch."""
    with Path(png).open('rb') as source:
        header = source.read(24)
    if header[:8] != b'\x89PNG\r\n\x1a\n' or len(header) != 24:
        raise ValueError('selected-row reader requires a PNG screenshot')
    width, height = struct.unpack_from('>II', header, 16)
    rgb = run(['ffmpeg', '-v', 'error', '-i', str(png), '-f', 'rawvideo',
               '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
    if len(rgb) != width * height * 3:
        raise ValueError('screenshot RGB dimensions differ from PNG header')
    highlighted = []
    for y in range(16, height):
        row = rgb[y * width * 3:(y + 1) * width * 3]
        count = sum(row[x] > 140 and row[x + 1] > 100
                    and row[x + 2] < row[x] * 0.85 and row[x + 1] > row[x + 2] * 1.1
                    for x in range(0, len(row), 3))
        if count > width // 2:
            highlighted.append(y)
    state = dict(selected='', selected_variants=[], cursor=None)
    if not highlighted:
        return state
    state['cursor'] = [min(highlighted), max(highlighted)]
    top, bottom = max(0, min(highlighted) - 1), min(height - 1, max(highlighted) + 1)
    crop = f'crop={width - 18}:{bottom - top + 1}:18:{top},'
    variants = (
        ('threshold8-psm7', 'scale=iw*8:ih*8:flags=neighbor,format=gray,'
         r'lut=y=if(lt(val\,100)\,0\,255),pad=iw+32:ih+32:16:16:white', 7),
        ('lanczos4-psm7', 'scale=iw*4:ih*4:flags=lanczos,format=gray,'
         'pad=iw+32:ih+32:16:16:white', 7),
        ('nearest4-psm7', 'scale=iw*4:ih*4:flags=neighbor,format=gray,'
         'pad=iw+32:ih+32:16:16:white', 7),
        ('nearest8-psm13', 'scale=iw*8:ih*8:flags=neighbor,format=gray,'
         'pad=iw+32:ih+32:16:16:white', 13),
    )
    for name, filters, mode in variants:
        text = ocr_image(png, crop + filters, mode)
        state['selected_variants'].append(dict(name=name, text=text))
        if len(state['selected_variants']) == 1:
            state['selected'] = text  # Preserve the original reader's raw output.
        if expected is None or selected_matches(expected, text):
            break
    return state


class Simulator:
    def __init__(self, build, root, results):
        self.build, self.root, self.results = build, root, results
        self.proc = None
        self.sequence = 0
        self.home_index = 0
        self.log = (results / 'startup.log').open('w')
        self.assertions = (results / 'assertions.jsonl').open('w', encoding='utf-8')

    def launch(self):
        self.proc = subprocess.Popen([str(self.build / 'rockboxui'), '--nobackground',
                                      '--root', str(self.root)], cwd=self.build,
                                     env=dict(os.environ, SDL_AUDIODRIVER='dummy'),
                                     stdout=self.log, stderr=subprocess.STDOUT)
        time.sleep(9)
        self.alive()
        window = run(['xdotool', 'search', '--sync', '--pid', str(self.proc.pid)],
                     capture_output=True, text=True).stdout.splitlines()[0]
        run(['xdotool', 'windowfocus', '--sync', window])
        self.geometry = dict(line.split('=', 1) for line in run(
            ['xdotool', 'getwindowgeometry', '--shell', window],
            capture_output=True, text=True).stdout.splitlines())

    def alive(self):
        assert self.proc.poll() is None, f'simulator exited: {self.proc.returncode}'

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    def key(self, name, count=1):
        for _ in range(count):
            self.alive()
            run(['xdotool', 'keydown', name])
            time.sleep(0.15)  # Longer than Rockbox sampling/debounce.
            run(['xdotool', 'keyup', name])
            time.sleep(0.35)

    def home(self):
        run(['xdotool', 'keydown', 'equal', 'minus'])
        time.sleep(0.15)
        run(['xdotool', 'keyup', 'equal', 'minus'])
        time.sleep(0.6)
        self.expect('home', selected=('Artists', 'Albums', 'Search')[self.home_index])

    def route(self, index):
        self.home()
        difference = index - self.home_index
        self.key('Down' if difference > 0 else 'Up', abs(difference))
        self.home_index = index
        self.expect('home-route', selected=('Artists', 'Albums', 'Search')[index])
        self.key('Return')

    def capture(self, label, expected_selected=None):
        self.alive()
        self.sequence += 1
        stem = self.results / f'{self.sequence:03d}-{label}'
        png = stem.with_suffix('.png')
        g = self.geometry
        # This is a single raw X11 frame with known geometry/rate. Avoid
        # libavformat probing megabytes of future frames before returning it.
        # https://ffmpeg.org/ffmpeg-formats.html#Format-Options
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'x11grab',
             '-probesize', '32', '-analyzeduration', '0', '-framerate', '30', '-video_size',
             g['WIDTH'] + 'x' + g['HEIGHT'], '-i',
             os.environ['DISPLAY'] + '+' + g['X'] + ',' + g['Y'],
             '-frames:v', '1', str(png)])
        text = ocr_image(png, 'scale=iw*6:ih*6:flags=neighbor,format=gray', 6)
        stem.with_suffix('.txt').write_text(text, encoding='utf-8')
        # Locate the default theme's yellow list cursor. OCR this isolated row
        # separately, so a merely visible item cannot satisfy selection checks.
        selected = read_selected(png, expected_selected)
        stem.with_name(stem.name + '-selected.txt').write_text(selected['selected'], encoding='utf-8')
        stem.with_name(stem.name + '-selected-variants.json').write_text(
            json.dumps(selected['selected_variants'], indent=2) + '\n', encoding='utf-8')
        return dict(image=png.name, text=text, **selected)

    def expect(self, label, *, selected=None, contains=(), absent=()):
        # Retry only screen rendering/OCR, never navigation. Each attempt is
        # retained, including failures, and final failure exits nonzero.
        for attempt in range(3):
            state = self.capture(label, selected)
            full = normalized(state['text'])
            errors = []
            if selected and not any(selected_matches(selected, variant['text'])
                                    for variant in state['selected_variants']):
                errors.append(f'selected {selected!r}, observed {state["selected_variants"]!r}')
            errors += [f'missing {value!r}' for value in contains if normalized(value) not in full]
            errors += [f'unexpected {value!r}' for value in absent if normalized(value) in full]
            self.assertions.write(json.dumps(dict(label=label, attempt=attempt + 1,
                expected=dict(selected=selected, contains=contains, absent=absent),
                observed=state, passed=not errors, errors=errors)) + '\n')
            self.assertions.flush()
            if not errors:
                return state
            time.sleep(0.5)
        raise AssertionError(f'{label}: {errors}; see {state["image"]}')

    def same_view(self, before, after):
        # Statusbar clock/battery are outside this comparison. Match the list
        # viewport's exact RGB bytes as well as its selected row and OCR text.
        def pixels(state):
            return run(['ffmpeg', '-v', 'error', '-i', str(self.results / state['image']),
                        '-vf', 'crop=iw:ih-20:0:20', '-f', 'rawvideo', '-pix_fmt',
                        'rgb24', '-'], capture_output=True).stdout
        assert before['cursor'] == after['cursor'], 'restored cursor moved within viewport'
        assert pixels(before) == pixels(after), 'restored scrolled viewport differs'

    def close(self):
        self.stop()
        self.log.close()
        self.assertions.close()


def database_status(root):
    """Retain only disposable database filenames, sizes and small header prefixes."""
    status = {}
    for path in sorted((root / '.rockbox').glob('database*')):
        if not path.is_file():
            continue
        with path.open('rb') as source:
            prefix = source.read(24)
        item = dict(size=path.stat().st_size, header_hex=prefix.hex())
        if len(prefix) >= 12:
            # apps/tagcache.c tagcache_header: int32 magic/datasize/entry_count.
            for byteorder in ('<', '>'):
                magic, size, count = struct.unpack_from(byteorder + 'III', prefix)
                item['little_endian' if byteorder == '<' else 'big_endian'] = dict(
                    magic=hex(magic), datasize=size, entry_count=count)
                if magic == 0x54434810:
                    item.update(magic=hex(magic), indexed_tracks=count, byteorder=byteorder)
                    if path.name == 'database_idx.tcd' and len(prefix) >= 24:
                        item['dirty'] = struct.unpack_from(byteorder + 'I', prefix, 20)[0]
        status[path.name] = item
    return status


def initialize(sim, track_count):
    started = time.monotonic()
    deadline = started + 180
    history = []

    def record(phase):
        files = database_status(sim.root)
        if not history or history[-1]['phase'] != phase or history[-1]['files'] != files:
            history.append(dict(phase=phase, elapsed=round(time.monotonic() - started, 2), files=files))
            (sim.results / 'database-initialization.json').write_text(json.dumps(
                dict(expected_tracks=track_count, history=history), indent=2) + '\n')
        return files

    try:
        sim.launch()
        sim.expect('initial-home', selected='Artists')
        sim.key('Return')
        sim.capture('initialize-prompt')
        sim.key('Return')
        while time.monotonic() < deadline:
            sim.alive()
            files = record('scanning')
            # Background commit may deliberately lack a temp buffer. Rockbox
            # then retains database_tmp.tcd and commits it on the next boot,
            # where tagcache_thread() calls allocate_tempbuf() in foreground.
            # Its scan header is finalized only after every input was scanned.
            if any(files.get(name, {}).get('indexed_tracks') == track_count
                   for name in ('database_tmp.tcd', 'database_idx.tcd')):
                time.sleep(3)
                record('before-required-restart')
                sim.stop()
                sim.launch()
                break
            time.sleep(0.5)
        else:
            raise AssertionError(f'database never scanned all {track_count} synthetic tracks')

        while time.monotonic() < deadline:
            sim.alive()
            master = record('committing-after-restart').get('database_idx.tcd', {})
            if master.get('indexed_tracks') == track_count and master.get('dirty') == 0:
                (sim.results / 'database-header.json').write_text(json.dumps(master) + '\n')
                sim.expect('initialized-home', selected='Artists')
                sim.key('Return')
                return
            time.sleep(0.5)
        raise AssertionError(f'database never committed all {track_count} synthetic tracks after restart')
    except Exception:
        record('failure')
        # Preserve the actual UI plus parsed/hex database headers before the
        # temporary root is removed. Diagnostics must not hide the first error.
        try:
            sim.capture('initialize-failure')
        except Exception as diagnostic_error:
            (sim.results / 'initialize-capture-error.txt').write_text(str(diagnostic_error) + '\n')
        raise


def library_checks(sim):
    sim.expect('artists-root', selected='All tracks')
    sim.key('Down', 23)  # Two shortcuts, Aster, Bison BB..CF (indices 0..20).
    scrolled = sim.expect('artists-scrolled', selected='Bison CF')
    sim.key('Return')
    sim.key('Down', 3)
    sim.expect('bison-album', selected='Opus CF')
    sim.key('Return')
    sim.expect('bison-tracks', selected='Tune One')
    sim.home()
    sim.key('Return')
    sim.expect('same-route-depth-restored', selected='Tune One')
    sim.key('Left')
    sim.expect('back-album-selection', selected='Opus CF')
    sim.key('Left')
    back = sim.expect('back-artist-selection', selected='Bison CF')
    sim.same_view(scrolled, back)

    sim.route(1)
    sim.key('Down', 3)
    sim.expect('global-delta-selected', selected='Delta')
    sim.key('Return')
    for index, title in enumerate(('One', 'Two', 'Three', 'Four')):
        sim.expect(f'multidisc-{index}', selected=title)
        if index < 3:
            sim.key('Down')
    sim.route(0)
    restored = sim.expect('artists-restored-after-albums', selected='Bison CF')
    sim.same_view(scrolled, restored)
    sim.route(1)
    sim.expect('albums-depth-selection-restored', selected='Four')
    sim.key('Left')
    sim.expect('albums-parent-selection', selected='Delta')
    sim.key('Down')
    sim.expect('global-echo-selected', selected='Echo')
    sim.key('Return')
    sim.expect('global-shared-album-first', selected='Amber')
    sim.key('Down')
    sim.expect('global-shared-album-second', selected='Indigo')
    sim.key('Down')
    sim.expect('global-shared-album-wrap-two-tracks', selected='Amber')

    sim.route(0)
    sim.key('Up', 21)
    sim.expect('aster-selected', selected='Aster')
    sim.key('Return')
    sim.key('Down', 4)
    sim.expect('aster-echo-selected', selected='Echo')
    sim.key('Return')
    sim.expect('aster-echo-isolated', selected='Amber')
    sim.key('Down')
    sim.expect('aster-echo-wrap-one-track', selected='Amber')
    sim.key('Left', 2)
    sim.key('Up', 3)  # Wrap from Aster through the shortcuts to the last artist.
    sim.expect('zulu-selected', selected='Zulu')
    sim.key('Return')
    sim.key('Down', 3)
    sim.expect('zulu-echo-selected', selected='Echo')
    sim.key('Return')
    sim.expect('zulu-echo-isolated', selected='Indigo')
    sim.key('Down')
    sim.expect('zulu-echo-wrap-one-track', selected='Indigo')


def search_checks(sim):
    sim.route(2)
    sim.expect('search-root', selected='Artist')
    sim.key('Down', 3)
    sim.expect('first-letter-selected', selected='First Letter')
    sim.key('Return')
    sim.expect('first-letter-kinds', selected='Artists')
    sim.key('Return')
    sim.key('Down')  # Numeric group precedes A.
    sim.expect('letter-a-selected', selected='A')
    sim.key('Return')
    sim.key('Down', 2)
    sim.expect('letter-a-results', selected='Aster')
    sim.key('Down')
    sim.expect('letter-a-wrap-one-artist', selected='All tracks')
    sim.key('Left', 2)
    sim.expect('first-letter-kinds-return', selected='Artists')
    sim.key('Down')
    sim.expect('first-letter-albums-kind-selected', selected='Albums')
    sim.key('Return')
    sim.key('Down', 4)  # Numeric, A, B, C, D.
    sim.expect('letter-d-selected', selected='D')
    sim.key('Return')
    sim.key('Down', 3)
    sim.expect('letter-d-albums', selected='Delta')
    sim.key('Down')
    sim.expect('letter-d-wrap-one-album', selected='By album')
    sim.key('Down')
    sim.expect('letter-d-second-shortcut', selected='All tracks')
    sim.key('Left', 3)
    sim.expect('search-root-return', selected='First Letter')
    sim.key('Up', 3)
    for index, (kind, value, shortcut_count) in enumerate((
            ('Artist', 'Aster', 2), ('Album', 'Delta', 3), ('Title', 'Amber', 0))):
        sim.expect(f'query-{kind}-selected', selected=kind)
        sim.key('Return')
        sim.capture(f'query-{kind}-keyboard')
        # Actual Rocker keyboard: initial picker cell A; Select inserts it,
        # physical Up accepts. No xdotool type, injected search clause, or API.
        sim.key('Return')
        sim.capture(f'query-{kind}-a-entered')
        sim.key('Up')
        sim.key('Down', shortcut_count)
        sim.expect(f'query-{kind}-a-results', selected=value)
        sim.key('Down')
        wrapped = {'Artist': 'All tracks', 'Album': 'By album', 'Title': 'Amber'}[kind]
        sim.expect(f'query-{kind}-wrap-one-result', selected=wrapped)
        if kind == 'Album':
            sim.key('Down')
            sim.expect('query-Album-second-shortcut', selected='All tracks')
        sim.key('Left')
        sim.expect(f'query-{kind}-back', selected=kind)
        if index < 2:
            sim.key('Down')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    args = parser.parse_args()
    if os.name != 'posix' or not os.environ.get('DISPLAY'):
        parser.error('run only in an isolated Linux Xvfb display')
    for tool in ('ffmpeg', 'ffprobe', 'xdotool', 'tesseract'):
        if not shutil.which(tool):
            parser.error(f'missing runner dependency: {tool}')
    build = args.build.resolve()
    results = build / 'library-results'
    results.mkdir(exist_ok=True)
    # Avoid presenting stale success from an earlier invocation.
    (results / 'passed.json').unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='emepetres-library-') as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(build / 'rockbox.zip') as archive:
            archive.extractall(root)
        expected = Path('apps/tagnavi-emepetres.config').read_bytes()
        assert (root / '.rockbox/tagnavi.config').read_bytes() == expected
        (root / '.rockbox/config.cfg').write_text(
            'start in screen: root\nbacklight timeout: 0\nlist wraparound: on\n', encoding='utf-8')
        fixture = create_library(root / 'Synthetic music', results / 'fixture.json')
        sim = Simulator(build, root, results)
        try:
            initialize(sim, fixture['tracks'])
            library_checks(sim)
            search_checks(sim)
            sim.alive()
            (results / 'passed.json').write_text(json.dumps(dict(
                fixture=fixture, screenshots=sim.sequence,
                checks=['artists-scroll-and-home', 'route-depth-selection-isolation',
                        'artist-album-name-collision', 'global-album-name-collision',
                        'multidisc-order', 'artist-and-album-first-letter',
                        'artist-album-title-query-a'])) + '\n')
            print(f'{build.name}: library runtime assertions passed ({fixture})')
        finally:
            sim.close()


if __name__ == '__main__':
    main()
