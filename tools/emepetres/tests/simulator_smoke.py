#!/usr/bin/env python3
"""Runtime smoke and review screenshots, using only generated audio in a temp root.

This is intentionally not a claim of complete navigation or hardware validation.
It verifies startup/package integration and records the first library screens.
"""
import os
from pathlib import Path
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
        'start in screen: root\nbacklight timeout: 0\n', encoding='utf-8')
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
    def launch():
        proc = subprocess.Popen([str(build / 'rockboxui'), '--nobackground',
                                 '--root', str(sandbox)], env=env, cwd=build,
                                stdout=log, stderr=subprocess.STDOUT)
        time.sleep(4)
        assert proc.poll() is None, 'simulator exited during startup'
        window = subprocess.check_output(
            ['xdotool', 'search', '--sync', '--pid', str(proc.pid)], timeout=10,
            text=True).splitlines()[0]
        subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)
        geometry = dict(line.split('=', 1) for line in subprocess.check_output(
            ['xdotool', 'getwindowgeometry', '--shell', window], text=True).splitlines())
        return proc, geometry

    def stop(proc):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    proc, geometry = launch()
    try:

        def key(name):
            # Rockbox samples and debounces button state twice; xdotool's
            # default 12 ms tap is too short to guarantee either sample.
            subprocess.run(['xdotool', 'keydown', name], check=True)
            time.sleep(0.15)
            subprocess.run(['xdotool', 'keyup', name], check=True)
            time.sleep(0.6)

        def capture(name):
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'x11grab',
                            '-video_size', geometry['WIDTH'] + 'x' + geometry['HEIGHT'],
                            '-i', os.environ['DISPLAY'] + '+' + geometry['X'] + ',' + geometry['Y'],
                            '-frames:v', '1', str(results / f'{name}.png')], check=True)

        capture('01-home')
        key('Return')  # Database is first in the Rocker default Home.
        time.sleep(1.5)
        capture('02-library-or-initialize')
        key('Return')  # Accept database initialization in this disposable root.
        for _ in range(30):
            if list((sandbox / '.rockbox').glob('database_*.tcd')):
                break
            time.sleep(0.5)
        time.sleep(2)
        assert proc.poll() is None, 'simulator exited while opening the database'
        assert list((sandbox / '.rockbox').glob('database_*.tcd')), 'database was not initialized'
        # Rockbox requires a restart after first initialization to activate the
        # database. Reopen the same disposable root before reviewing the menu.
        stop(proc)
        proc, geometry = launch()
        key('Return')
        capture('03-library-after-restart')
        key('Return')
        capture('04-artists')
        assert proc.poll() is None, 'simulator exited while browsing initialized database'
        print(f'{build.name}: package, startup, database initialization and reopening passed')
    finally:
        stop(proc)
        log.close()
        print((results / 'startup.log').read_text(errors='replace')[-4000:])
