"""Explicit, read-only discovery of known exports at removable-volume roots."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
import stat

DEDICATED = '.emepetres-scrobbler.log'
LEGACY = ('.scrobbler.log', '.scrobbler-timeless.log')
DEVICE_HELP = ('Conecta el Rocker por USB y comprueba que Windows muestra su tarjeta. '
               'En el reproductor usa Last.fm → Preparar sincronizacion antes de conectarlo '
               'y vuelve a pulsar «Importar del Rocker». También puedes usar '
               '«Importar registro…» para elegir una copia local.')


class DeviceUnavailableError(FileNotFoundError):
    """The selected removable export vanished or is no longer a plain file."""


def _windows_api():
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.GetLogicalDrives.argtypes = []
    api.GetLogicalDrives.restype = wintypes.DWORD
    api.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    api.GetDriveTypeW.restype = wintypes.UINT
    return api


def removable_roots():
    """List DRIVE_REMOVABLE letters only; never stat or enumerate a volume."""
    api = _windows_api()
    if api is None:
        return []
    mask = api.GetLogicalDrives()
    return [Path(root) for index in range(26) if mask & (1 << index)
            for root in (f'{chr(65 + index)}:\\',) if api.GetDriveTypeW(root) == 2]


def _plain(path, *, directory=False):
    """Reject UNC/device paths and every symlink/reparse component, without resolving."""
    text = str(path)
    if PureWindowsPath(text).drive.startswith('\\\\') or not path.is_absolute():
        return False
    try:
        # Parents are checked before children so a junction is never traversed.
        for parent in reversed(path.parents):
            info = parent.lstat()
            if (not stat.S_ISDIR(info.st_mode) or
                    getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                return False
        info = path.lstat()
        return (not getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)))
    except OSError:
        # Ejected, inaccessible or unready media is a normal discovery result.
        return False


def is_export(path):
    """Recheck a chosen candidate immediately before the import worker reads it."""
    path = Path(path)
    return path.name in (DEDICATED, *LEGACY) and _plain(path)


def find_exports(roots):
    """Inspect only known filenames, preferring the dedicated log on each root.

    Explicit roots permit isolated tests; production roots come exclusively from
    removable_roots(), which excludes network and fixed drives. No contents are
    read here, no directories listed and no device files modified.
    """
    found, seen = [], set()
    for root in roots:
        root = Path(root)
        if root in seen:
            continue
        seen.add(root)
        if not _plain(root, directory=True):
            continue
        preferred = root / DEDICATED
        if is_export(preferred):
            found.append(preferred)
        else:
            found.extend(root / name for name in LEGACY if is_export(root / name))
    return found
