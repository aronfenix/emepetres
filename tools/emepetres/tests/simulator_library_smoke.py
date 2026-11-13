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

    def ocr(self, png, filters, mode):
        enlarged = run(['ffmpeg', '-v', 'error', '-i', str(png), '-vf', filters,
                        '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-'],
                       capture_output=True).stdout
        return run(['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', str(mode)],
                   input=enlarged, capture_output=True).stdout.decode('utf-8')

    def capture(self, label):
        self.alive()
        self.sequence += 1
        stem = self.results / f'{self.sequence:03d}-{label}'
        png = stem.with_suffix('.png')
        g = self.geometry
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'x11grab', '-video_size',
             g['WIDTH'] + 'x' + g['HEIGHT'], '-i',
             os.environ['DISPLAY'] + '+' + g['X'] + ',' + g['Y'],
             '-frames:v', '1', str(png)])
        text = self.ocr(png, 'scale=iw*6:ih*6:flags=neighbor,format=gray', 6)
        stem.with_suffix('.txt').write_text(text, encoding='utf-8')
        # Locate the default theme's yellow list cursor. OCR this isolated row
        # separately, so a merely visible item cannot satisfy selection checks.
        rgb = run(['ffmpeg', '-v', 'error', '-i', str(png), '-f', 'rawvideo',
                   '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
        width, height = int(g['WIDTH']), int(g['HEIGHT'])
        highlighted = []
        for y in range(16, height):
            row = rgb[y * width * 3:(y + 1) * width * 3]
            count = sum(row[x] > 140 and row[x + 1] > 100
                        and row[x + 2] < row[x] * 0.85 and row[x + 1] > row[x + 2] * 1.1
                        for x in range(0, len(row), 3))
            if count > width // 2:
                highlighted.append(y)
        selected = ''
        if highlighted:
            top, bottom = max(0, min(highlighted) - 1), min(height - 1, max(highlighted) + 1)
            filters = (f'crop={width - 18}:{bottom - top + 1}:18:{top},'
                       'scale=iw*8:ih*8:flags=neighbor,format=gray,'
                       r'lut=y=if(lt(val\,100)\,0\,255),pad=iw+32:ih+32:16:16:white')
            selected = self.ocr(png, filters, 7)
        stem.with_name(stem.name + '-selected.txt').write_text(selected, encoding='utf-8')
        return dict(image=png.name, text=text, selected=selected,
                    cursor=[min(highlighted), max(highlighted)] if highlighted else None)

    def expect(self, label, *, selected=None, contains=(), absent=()):
        # Retry only screen rendering/OCR, never navigation. Each attempt is
        # retained, including failures, and final failure exits nonzero.
        for attempt in range(3):
            state = self.capture(label)
            full, row = normalized(state['text']), normalized(state['selected'])
            errors = []
            if selected and normalized(selected) not in row:
                errors.append(f'selected {selected!r}, observed {state["selected"]!r}')
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


def initialize(sim, track_count):
    sim.launch()
    sim.expect('initial-home', selected='Artists')
    sim.key('Return')
    sim.capture('initialize-prompt')
    sim.key('Return')
    master = sim.root / '.rockbox/database_idx.tcd'
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        sim.alive()
        data = master.read_bytes() if master.exists() else b''
        # apps/tagcache.c tagcache_header: three int32 fields, magic/size/count.
        if len(data) >= 24:
            for byteorder in ('<', '>'):
                magic, _, count = struct.unpack_from(byteorder + 'III', data)
                if magic == 0x54434810 and count == track_count:
                    time.sleep(3)
                    (sim.results / 'database-header.json').write_text(json.dumps(
                        dict(magic=hex(magic), indexed_tracks=count, byteorder=byteorder)) + '\n')
                    sim.stop()
                    sim.launch()
                    sim.key('Return')
                    return
        time.sleep(0.5)
    raise AssertionError(f'database never committed all {track_count} synthetic tracks')


def library_checks(sim):
    sim.expect('artists-root', contains=('Aster', 'Bison 000'), selected='All tracks')
    sim.key('Down', 23)  # Two shortcuts, Aster, Bison 000..020.
    scrolled = sim.expect('artists-scrolled', selected='Bison 020', absent=('Aster',))
    sim.key('Return')
    sim.key('Down', 3)
    sim.expect('bison-album', selected='Opus 020')
    sim.key('Return')
    sim.expect('bison-tracks', selected='Tune 001')
    sim.home()
    sim.key('Return')
    sim.expect('same-route-depth-restored', selected='Tune 001')
    sim.key('Left')
    sim.expect('back-album-selection', selected='Opus 020')
    sim.key('Left')
    back = sim.expect('back-artist-selection', selected='Bison 020')
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
    restored = sim.expect('artists-restored-after-albums', selected='Bison 020')
    sim.same_view(scrolled, restored)
    sim.route(1)
    sim.expect('albums-depth-selection-restored', selected='Four')
    sim.key('Left')
    sim.expect('albums-parent-selection', selected='Delta')
    sim.key('Down')
    sim.expect('global-echo-selected', selected='Echo')
    sim.key('Return')
    sim.expect('global-shared-album', contains=('Amber', 'Indigo'))

    sim.route(0)
    sim.key('Up', 21)
    sim.expect('aster-selected', selected='Aster')
    sim.key('Return')
    sim.key('Down', 4)
    sim.expect('aster-echo-selected', selected='Echo')
    sim.key('Return')
    sim.expect('aster-echo-isolated', selected='Amber', absent=('Indigo',))
    sim.key('Left', 2)
    sim.key('Up', 3)  # Wrap from Aster through the shortcuts to the last artist.
    sim.expect('zulu-selected', selected='Zulu')
    sim.key('Return')
    sim.key('Down', 3)
    sim.expect('zulu-echo-selected', selected='Echo')
    sim.key('Return')
    sim.expect('zulu-echo-isolated', selected='Indigo', absent=('Amber',))


def search_checks(sim):
    sim.route(2)
    sim.expect('search-root', selected='Artist', contains=('Album', 'Title', 'First Letter'))
    sim.key('Down', 3)
    sim.expect('first-letter-selected', selected='First Letter')
    sim.key('Return')
    sim.expect('first-letter-kinds', selected='Artists', contains=('Albums',))
    sim.key('Return')
    sim.key('Down')  # Numeric group precedes A.
    sim.expect('letter-a-selected', selected='A')
    sim.key('Return')
    sim.key('Down', 2)
    sim.expect('letter-a-results', selected='Aster', absent=('Bison', 'Zulu'))
    sim.key('Left', 2)
    sim.expect('first-letter-kinds-return', selected='Artists')
    sim.key('Down')
    sim.key('Return')
    sim.key('Down', 4)  # Numeric, A, B, C, D.
    sim.expect('letter-d-selected', selected='D')
    sim.key('Return')
    sim.key('Down', 3)
    sim.expect('letter-d-albums', selected='Delta', absent=('Echo', 'Opus'))
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
        sim.expect(f'query-{kind}-a-results', selected=value,
                   absent=('Bison', 'Opus', 'Tune', 'Zulu', 'Indigo'))
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
