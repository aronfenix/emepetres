"""Explicit preview, authorization and single-batch sync commands."""
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys
import webbrowser

from . import engine


def parser():
    result = argparse.ArgumentParser(description='emepetres Last.fm: importa y revisa antes de enviar.')
    result.add_argument('--data-dir', type=Path, default=None, help='Carpeta de datos locales')
    result.add_argument('--smoke', action='store_true', help=argparse.SUPPRESS)
    commands = result.add_subparsers(dest='command')
    gui = commands.add_parser('gui', help='Abrir la ventana; no conecta al iniciar')
    gui.add_argument('--smoke', dest='gui_smoke', action='store_true', help=argparse.SUPPRESS)
    preview = commands.add_parser('preview', help='Importar y mostrar sin enviar nada')
    preview.add_argument('--account', required=True)
    preview.add_argument('--import', dest='imports', action='append', type=Path, default=[], metavar='REGISTRO')
    preview.add_argument('--status', choices=engine.STATES)
    preview.add_argument('--limit', type=int, default=100)
    commands.add_parser('connect', help='Autorizar una cuenta y guardar las claves con Windows')
    sync = commands.add_parser('sync', help='ENVIAR un único lote a Last.fm de forma explícita')
    sync.add_argument('--account', required=True)
    sync.add_argument('--maximum', type=int, default=50, choices=range(1, 51), metavar='1..50')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    directory = args.data_dir or engine.default_data_dir()
    try:
        if args.command in (None, 'gui'):
            from .gui import run
            return run(directory, smoke=args.smoke or getattr(args, 'gui_smoke', False))
        if args.command == 'connect':
            from .credentials import Vault
            key = getpass.getpass('API key: ')
            secret = getpass.getpass('Secreto de aplicación: ')
            client = engine.Client(key.strip(), secret.strip())
            token, url = client.begin_auth()
            if not webbrowser.open(url):
                raise RuntimeError('No se pudo abrir el navegador predeterminado.')
            input('Autoriza la aplicación en Last.fm y pulsa Intro para terminar: ')
            name, session = client.finish_auth(token)
            vault = Vault(directory)
            settings = vault.load()
            sessions = dict(settings.get('sessions', {})) if settings.get('api_key') == key.strip() else {}
            sessions[engine.account_id(name)] = session
            settings.update(api_key=key.strip(), secret=secret.strip(), account=name, sessions=sessions)
            vault.save(settings)
            print(f'Cuenta {name} autorizada. No se ha enviado ninguna escucha.')
            return 0
        ledger = engine.Ledger(directory)
        try:
            account = engine.account_id(args.account)
            if args.command == 'preview':
                if args.limit < 0:
                    raise ValueError('El límite debe ser positivo.')
                imports = []
                for source in args.imports:
                    result = ledger.import_file(source, account)
                    imports.append({'added': result.added, 'duplicates': result.duplicates,
                                    'upgraded': result.upgraded, 'archive': result.backup})
                rows = [dict(row) for row in ledger.rows(account, args.status)][:args.limit]
                print(json.dumps({'account': account, 'imports': imports,
                                  'counts': ledger.counts(account), 'rows': rows}, ensure_ascii=False, indent=2))
            elif args.command == 'sync':
                from .credentials import Vault
                settings = Vault(directory).load()
                session = settings.get('sessions', {}).get(account)
                if not session:
                    raise ValueError('Autoriza primero esta cuenta Last.fm.')
                result = engine.SyncEngine(ledger, engine.Client(settings.get('api_key', ''), settings.get('secret', '')),
                                           account, session).sync(maximum=args.maximum)
                print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            ledger.close()
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        # Never print raw exception data: transports may echo submitted secrets.
        if isinstance(exc, engine.APIError):
            message = f'Last.fm código {exc.code}; comprueba la autorización.'
        elif isinstance(exc, KeyboardInterrupt):
            message = 'Operación cancelada. Revisa los estados antes de volver a enviar.'
        else:
            message = 'No se pudo completar la operación. Revisa la cuenta, el archivo, la conexión y las credenciales locales.'
        print(message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
