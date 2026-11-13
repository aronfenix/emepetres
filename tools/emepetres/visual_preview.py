#!/usr/bin/env python3
"""Package a visual-only overlay and capture it in an existing Rocker simulator.

Never accesses a device or a user library. No firmware compilation or OCR.
Fonts are built beforehand using Rockbox's convbdf, not another font converter.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / 'visual-output'
OVERLAY = OUT / 'overlay'
BUILD = REPO / 'build-agptekrocker'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def package():
    theme = REPO / 'wps/emepetres'
    for name in ('emepetres.sbs', 'emepetres.wps'):
        target = OVERLAY / '.rockbox/wps' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(theme / name, target)
    target = OVERLAY / '.rockbox/themes/emepetres.cfg'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(theme / 'emepetres.cfg', target)
    activation = (theme / 'emepetres.cfg').read_text(encoding='utf-8')
    (OVERLAY / 'EMEPETRES-VISUAL.cfg').write_text(activation, encoding='utf-8')
    (OVERLAY / 'LEEME.txt').write_text(
        'Actualización visual de emepetres. No contiene update.upt.\n'
        'Conserva una copia de .rockbox/config.cfg antes de activar el diseño.\n'
        'Combina la carpeta .rockbox con la existente; no borres la anterior.\n'
        'Copia también EMEPETRES-VISUAL.cfg a la raíz de la tarjeta.\n'
        'Abre Sistema > Archivos y selecciona EMEPETRES-VISUAL.cfg.\n'
        'También puedes elegir emepetres desde Ajustes > Temas > Explorar temas.\n'
        'No se modifica el programa, la base de datos, la música ni los registros.\n'
        'No hay que ejecutar Actualizar firmware otra vez.\n', encoding='utf-8')
    shutil.copyfile(REPO / 'firmware/COPYING', OVERLAY / 'LICENCIA-GPL.txt')
    for name in ('14-Nimbus', '19-Nimbus'):
        font = OVERLAY / f'.rockbox/fonts/{name}.fnt'
        assert font.read_bytes()[:4] == b'RB12', f'font missing or invalid: {font}'
        shutil.copyfile(REPO / f'fonts/{name}.bdf', OVERLAY / f'{name}-FUENTE.bdf')
    checks = {p.relative_to(OVERLAY).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(OVERLAY.rglob('*')) if p.is_file()}
    (OVERLAY / 'SHA256.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    with zipfile.ZipFile(OUT / 'emepetres-visual.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OVERLAY.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(OVERLAY).as_posix())


def preview():
    with tempfile.TemporaryDirectory(prefix='emepetres-visual-') as tmp:
        sandbox = Path(tmp)
        with zipfile.ZipFile(BUILD / 'rockbox.zip') as z:
            z.extractall(sandbox)
        shutil.copytree(OVERLAY / '.rockbox', sandbox / '.rockbox', dirs_exist_ok=True)
        config = (OVERLAY / 'EMEPETRES-VISUAL.cfg').read_text(encoding='utf-8')
        config += 'start in screen: root\nbacklight timeout: 0\n'
        (sandbox / '.rockbox/config.cfg').write_text(config, encoding='utf-8')
        music = sandbox / 'Demo'
        music.mkdir()
        for n, (artist, album, title) in enumerate([
            ('Nina Simone', 'Pastel Blues', 'Sinnerman'),
            ('Radiohead', 'In Rainbows', 'Nude'),
            ('The Cure', 'Disintegration', 'Pictures of You'),
        ]):
            run('ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo',
                '-t', '1', '-metadata', f'artist={artist}', '-metadata', f'album={album}',
                '-metadata', f'title={title}', '-metadata', 'track=1', str(music / f'{n}.flac'))
        env = dict(os.environ, SDL_AUDIODRIVER='dummy')
        log = (OUT / 'simulator.log').open('w')
        proc = None

        def launch():
            p = subprocess.Popen([str(BUILD / 'rockboxui'), '--nobackground', '--root', str(sandbox)],
                                 cwd=BUILD, env=env, stdout=log, stderr=subprocess.STDOUT)
            time.sleep(9)
            assert p.poll() is None, 'simulator closed during startup'
            window = subprocess.check_output(['xdotool', 'search', '--sync', '--pid', str(p.pid)],
                                             text=True, timeout=10).splitlines()[0]
            run('xdotool', 'windowfocus', '--sync', window)
            geometry = dict(line.split('=', 1) for line in subprocess.check_output(
                ['xdotool', 'getwindowgeometry', '--shell', window], text=True).splitlines())
            return p, geometry

        def key(name):
            run('xdotool', 'keydown', name)
            time.sleep(.15)
            run('xdotool', 'keyup', name)
            time.sleep(.6)

        def capture(name):
            run('ffmpeg', '-y', '-v', 'error', '-f', 'x11grab', '-probesize', '32',
                '-analyzeduration', '0', '-video_size', geometry['WIDTH'] + 'x' + geometry['HEIGHT'],
                '-i', os.environ['DISPLAY'] + '+' + geometry['X'] + ',' + geometry['Y'],
                '-frames:v', '1', str(OUT / (name + '.png')))

        def stop():
            if proc and proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)

        try:
            proc, geometry = launch()
            capture('01-inicio')
            key('Down'); key('Down'); key('Down'); key('Return')
            capture('02-lastfm')
            key('Left'); key('Up'); key('Up'); key('Up'); key('Return')
            key('Return')
            for _ in range(20):
                if list((sandbox / '.rockbox').glob('database_*.tcd')):
                    break
                time.sleep(.5)
            assert list((sandbox / '.rockbox').glob('database_*.tcd')), 'demo database not created'
            time.sleep(2)
            stop()
            proc, geometry = launch()
            key('Return')
            capture('03-artistas')
            key('Down'); key('Down'); key('Return')
            capture('04-albumes')
            key('Down'); key('Down'); key('Return')
            capture('05-canciones')
            assert proc.poll() is None
        finally:
            stop()
            log.close()
    print('Visual package built; five actual simulator screenshots captured; no device accessed.')


if __name__ == '__main__':
    package()
    preview()
