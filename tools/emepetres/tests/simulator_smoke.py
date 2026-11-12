#!/usr/bin/env python3
"""Runtime smoke and review screenshots, using only generated audio in a temp root.

This is intentionally not a claim of complete navigation or hardware validation.
It verifies startup/package integration and records the first library screens.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

build = Path(sys.argv[1]).resolve()
results = build / 'smoke-results'
results.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='emepetres-simulator-') as tmp:
    sandbox = Path(tmp)
    with zipfile.ZipFile(build / 'rockbox.zip') as archive:
        archive.extractall(sandbox)
    expected = Path('apps/tagnavi-emepetres.config').read_bytes()
    assert (sandbox / '.rockbox/tagnavi.config').read_bytes() == expected
    (sandbox / '.rockbox/config.cfg').write_text(
        'start in screen: root\nbacklight timeout: off\n', encoding='utf-8')
    music = sandbox / 'Synthetic music'
    music.mkdir()
    for artist in range(1, 4):
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=5', '-metadata',
                        f'artist=Test Artist {artist}', '-metadata',
                        'album=Test Album', '-metadata', 'title=Test Track',
                        '-metadata', 'track=1', str(music / f'artist-{artist}.flac')], check=True)
    env = dict(os.environ, SDL_AUDIODRIVER='dummy')
    log = (results / 'startup.log').open('w')
    proc = subprocess.Popen([str(build / 'rockboxui'), '--nobackground',
                             '--root', str(sandbox)], env=env, cwd=build,
                            stdout=log, stderr=subprocess.STDOUT)
    try:
        time.sleep(4)
        assert proc.poll() is None, 'simulator exited during startup'
        window = subprocess.check_output(
            ['xdotool', 'search', '--sync', '--pid', str(proc.pid)], timeout=10,
            text=True).splitlines()[0]
        subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)

        def key(name):
            subprocess.run(['xdotool', 'key', '--clearmodifiers', name], check=True)
            time.sleep(0.4)

        def capture(name):
            # Native simulators expose F5; hosted/application builds may not.
            before = set(sandbox.glob('*.bmp'))
            key('F5')
            for path in set(sandbox.glob('*.bmp')) - before:
                shutil.copyfile(path, results / f'{name}.bmp')

        capture('01-home')
        key('Return')  # Database is first in the Rocker default Home.
        capture('02-library-or-initialize')
        key('Return')  # Accept database initialization in this disposable root.
        time.sleep(8)
        capture('03-library-after-initialize')
        assert proc.poll() is None, 'simulator exited while opening the database'
        assert list((sandbox / '.rockbox').glob('database_*.tcd')), 'database was not initialized'
        print(f'{build.name}: package, startup and synthetic database initialization passed')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()
