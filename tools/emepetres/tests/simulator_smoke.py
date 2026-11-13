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
                        'sine=frequency=440:duration=31', '-metadata',
                        f'artist=Test Artist {artist}', '-metadata',
                        'album=Test Album', '-metadata', 'title=Test Track',
                        '-metadata', 'track=1', str(music / f'artist-{artist}.flac')], check=True)
    env = dict(os.environ, SDL_AUDIODRIVER='dummy')
    log = (results / 'startup.log').open('w')
    def launch():
        proc = subprocess.Popen([str(build / 'rockboxui'), '--nobackground',
                                 '--root', str(sandbox)], env=env, cwd=build,
                                stdout=log, stderr=subprocess.STDOUT)
        # The startup logo can still be visible at four seconds when logging
        # and the database are initialized. Do not send navigation into boot.
        time.sleep(9)
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
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'x11grab',
                            '-probesize', '32', '-analyzeduration', '0', '-framerate', '30',
                            '-video_size', geometry['WIDTH'] + 'x' + geometry['HEIGHT'],
                            '-i', os.environ['DISPLAY'] + '+' + geometry['X'] + ',' + geometry['Y'],
                            '-frames:v', '1', str(results / f'{name}.png')], check=True)

        def home():
            subprocess.run(['xdotool', 'keydown', 'equal', 'minus'], check=True)
            time.sleep(0.15)
            subprocess.run(['xdotool', 'keyup', 'equal', 'minus'], check=True)
            time.sleep(0.6)

        capture('01-home')
        key('Return')  # Artists opens directly from emepetres Home.
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
        capture('03-artists-direct')
        key('Down'); key('Down')  # Skip All Tracks and Random; choose Artist 1.
        capture('04-selected-artist')
        key('Return')
        capture('05-artist-albums')
        key('Down'); key('Down'); key('Down')  # Actual album after three shortcuts.
        key('Return')
        capture('06-album-tracks')
        key('Left')
        capture('07-back-preserved-album')
        key('Return')
        key('Return')  # Play the selected synthetic 31-second FLAC.
        capture('08-playback')
        raw = sandbox / '.rockbox/emepetres_playback.log'
        # Loading and dummy audio on a busy runner are not guaranteed to run at
        # wall-clock speed. Wait for the completed track's durable record rather
        # than treating 16 seconds of wall time as 16 seconds of consumed audio.
        for _ in range(90):
            rows = raw.read_text(errors='replace').splitlines() if raw.exists() else []
            if any(line and not line.startswith('#') and len(line.split(':', 3)) == 4
                   for line in rows):
                break
            assert proc.poll() is None, 'simulator exited during playback'
            time.sleep(1)
        else:
            raise AssertionError('synthetic playback did not finish within the runtime limit')
        time.sleep(1)
        home()  # Playback completion returns to the library; the chord opens Home.
        capture('09-home-after-playback')
        key('Down'); key('Down'); key('Down')  # Artists -> Albums -> Search -> Last.fm.
        key('Return')
        capture('10-lastfm')
        key('Return')  # Prepare synchronization, preserving raw source logs.
        time.sleep(6)
        capture('11-lastfm-export')
        exported = sandbox / '.emepetres-scrobbler.log'
        assert raw.is_file(), 'offline listening record missing'
        assert exported.is_file(), 'Last.fm export missing'
        lines = exported.read_text(encoding='utf-8-sig').splitlines()
        played = [line.split('\t') for line in lines if line and not line.startswith('#')]
        assert any(len(fields) >= 7 and fields[5] == 'L' and fields[0] == 'Test Artist 1'
                   and fields[2] == 'Test Track' and int(fields[6]) > 0 for fields in played), 'qualified synthetic scrobble missing'
        (results / 'synthetic-scrobbler.log').write_bytes(exported.read_bytes())
        previous_export = exported.read_bytes()
        previous_raw = raw.read_bytes()
        key('Return')  # Repeat export: snapshot is regenerated, not appended again.
        time.sleep(6)
        assert exported.read_bytes() == previous_export, 'repeated export duplicated retained history'
        assert raw.read_bytes() == previous_raw, 'export changed the raw listening record'
        assert proc.poll() is None, 'simulator exited while browsing initialized database'
        print(f'{build.name}: direct Artists/Albums/Tracks, Back, playback and offline Last.fm export passed')
    finally:
        stop(proc)
        log.close()
        print((results / 'startup.log').read_text(errors='replace')[-4000:])
