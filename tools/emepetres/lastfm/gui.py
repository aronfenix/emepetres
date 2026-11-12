"""Spanish, offline-first Tkinter interface for the account-bound ledger."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import webbrowser

from . import engine
from .credentials import Vault

LABELS = {
    'pending': 'Pendientes', 'sent': 'Enviadas', 'ignored': 'Omitidas',
    'review': 'Para revisar', 'uncertain': 'Sin confirmar', 'retry': 'Reintento',
    'auth_required': 'Autorizar de nuevo', 'rejected': 'Rechazadas',
    'sending': 'Envío interrumpido',
}


def safe_error(exc):
    """Do not surface transport bodies, URLs, tokens or credential values."""
    if isinstance(exc, engine.APIError):
        return f'Last.fm ha devuelto el código {exc.code}. Revisa la autorización.'
    if isinstance(exc, FileNotFoundError):
        return 'No se encuentra el archivo seleccionado.'
    if isinstance(exc, PermissionError):
        return 'No se puede acceder al archivo o guardar los datos locales.'
    if isinstance(exc, ValueError):
        return 'La operación no es válida para esta selección. Revisa los datos y el estado de las filas.'
    return 'No se pudo completar la operación. Revisa la conexión y vuelve a intentarlo manualmente.'


def account_session(settings, account):
    account = engine.account_id(account)
    session = settings.get('sessions', {}).get(account)
    if not session:
        raise ValueError('Autoriza primero esta cuenta Last.fm.')
    return account, session


class App:
    def __init__(self, root, directory):
        self.root, self.directory = root, Path(directory)
        self.vault = Vault(self.directory)
        self.settings = {}
        self.token = None
        self.busy = False
        self.events = queue.Queue()
        self.closed = False
        self.row_data = {}
        self.controls = []
        root.title('emepetres · Last.fm')
        root.geometry('1100x740')
        root.minsize(850, 600)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.account = tk.StringVar()
        self.api_key = tk.StringVar()
        self.secret = tk.StringVar()
        self.filter = tk.StringVar(value='Todos')
        self.status = tk.StringVar(value='Sin conexión de red. Importa un registro para revisarlo.')
        self.counts = tk.StringVar()
        self.connection = tk.StringVar(value='Cuenta sin autorizar')
        self._build()
        try:
            self.settings = self.vault.load()
            self.account.set(self.settings.get('account', ''))
            self.api_key.set(self.settings.get('api_key', ''))
            self.secret.set(self.settings.get('secret', ''))
        except Exception:
            self.status.set('No se pudieron abrir las credenciales protegidas. Puedes configurar la cuenta de nuevo.')
        ledger = engine.Ledger(self.directory)
        try:
            try:
                ledger.recover_interrupted()
            except RuntimeError:
                self.status.set('Hay otra sincronización activa. Espera antes de modificar o enviar escuchas.')
        finally:
            ledger.close()
        self.refresh()
        self.poll_after = root.after(100, self._poll)

    def button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        self.controls.append(button)
        return button

    def _build(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Tus escuchas, antes de enviarlas', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='1. Conecta tu cuenta   ·   2. Importa y revisa   ·   3. Envía un lote cuando quieras').pack(anchor='w', pady=(4, 12))
        setup = ttk.LabelFrame(outer, text='Cuenta y autorización', padding=10)
        setup.pack(fill='x')
        for row, (label, variable, masked) in enumerate((
                ('Cuenta Last.fm (también para vista previa)', self.account, False),
                ('API key de tu aplicación', self.api_key, True),
                ('Secreto de tu aplicación', self.secret, True))):
            ttk.Label(setup, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=3)
            entry = ttk.Entry(setup, textvariable=variable, show='•' if masked else '', width=48)
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            self.controls.append(entry)
        setup.columnconfigure(1, weight=1)
        self.button(setup, '1. Autorizar en Last.fm', self.begin_auth).grid(row=0, column=2, padx=12)
        self.button(setup, '2. Ya he autorizado', self.finish_auth).grid(row=1, column=2, padx=12)
        self.button(setup, 'Actualizar cuenta', self.refresh).grid(row=2, column=2, padx=12)
        ttk.Label(setup, textvariable=self.connection).grid(row=3, column=0, columnspan=3, sticky='w', pady=(5, 0))
        ttk.Label(setup, text='Las claves se guardan cifradas para tu usuario de Windows. No se envía nada al abrir la aplicación.').grid(row=4, column=0, columnspan=3, sticky='w')
        actions = ttk.Frame(outer)
        actions.pack(fill='x', pady=12)
        self.button(actions, 'Importar registro…', self.import_log).pack(side='left')
        self.button(actions, 'Enviar hasta 50 pendientes', self.sync).pack(side='left', padx=8)
        self.button(actions, 'Copia de seguridad', self.backup).pack(side='left')
        self.button(actions, 'Olvidar credenciales', self.forget).pack(side='right')
        ttk.Label(outer, textvariable=self.counts, wraplength=1000).pack(anchor='w', pady=(0, 8))
        filters = ttk.Frame(outer)
        filters.pack(fill='x')
        ttk.Label(filters, text='Mostrar:').pack(side='left')
        combo = ttk.Combobox(filters, textvariable=self.filter, state='readonly',
                             values=['Todos', *LABELS.values()], width=24)
        combo.pack(side='left', padx=6)
        combo.bind('<<ComboboxSelected>>', lambda event: self.refresh())
        self.controls.append(combo)
        ttk.Label(filters, text='Selecciona filas para confirmar zona o resolver un envío dudoso.').pack(side='left', padx=8)
        table = ttk.Frame(outer)
        table.pack(fill='both', expand=True, pady=8)
        self.tree = ttk.Treeview(table, columns=('state', 'date', 'artist', 'track', 'reason'), show='headings', selectmode='extended')
        for key, text, width in (('state', 'Estado', 120), ('date', 'Fecha UTC / reloj sin confirmar', 180),
                                  ('artist', 'Artista', 150), ('track', 'Título', 180), ('reason', 'Detalle', 360)):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, minwidth=80)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        review = ttk.Frame(outer)
        review.pack(fill='x')
        for text, command in (('Confirmar zona horaria…', self.confirm_timezone),
                              ('Ya consta en Last.fm', lambda: self.resolve('sent')),
                              ('Descartar envío dudoso', lambda: self.resolve('ignored')),
                              ('Permitir reenvío dudoso…', lambda: self.resolve('pending'))):
            self.button(review, text, command).pack(side='left', padx=(0, 6))
        ttk.Label(outer, textvariable=self.status, wraplength=1000).pack(anchor='w', pady=(12, 0))
        ttk.Label(outer, text='El registro del reproductor se abre solo para lectura. Las importaciones conservan una copia local exacta.').pack(anchor='w', pady=(4, 0))

    def current_account(self):
        return engine.account_id(self.account.get())

    def refresh(self):
        if self.busy:
            return
        self.tree.delete(*self.tree.get_children())
        self.row_data.clear()
        try:
            account = self.current_account()
        except ValueError:
            self.counts.set('Introduce una cuenta para ver o importar sus escuchas.')
            self.connection.set('Cuenta sin autorizar')
            return
        ledger = engine.Ledger(self.directory)
        try:
            counts = ledger.counts(account)
            state = next((key for key, label in LABELS.items() if label == self.filter.get()), None)
            for row in ledger.rows(account, state):
                item = dict(row)
                self.row_data[str(row['id'])] = item
                try:
                    date = datetime.fromtimestamp(row['timestamp'], timezone.utc).strftime('%Y-%m-%d %H:%M') if row['timestamp'] else 'Sin fecha'
                except (ValueError, OSError, OverflowError):
                    date = 'Fecha no válida'
                if row['timezone'] != 'UTC':
                    date += ' · sin confirmar'
                self.tree.insert('', 'end', iid=str(row['id']), values=(LABELS.get(row['status'], row['status']), date,
                                  row['artist'], row['track'], row['reason']))
            self.counts.set('   ·   '.join(f'{label}: {counts.get(key, 0)}' for key, label in LABELS.items()))
        finally:
            ledger.close()
        authorized = account in self.settings.get('sessions', {})
        self.connection.set(f'Cuenta: {account} · ' + ('Autorizada en este equipo' if authorized else 'Solo vista previa; autoriza antes de enviar'))

    def _job(self, work, success):
        if self.busy:
            return
        self.busy = True
        for control in self.controls:
            control.configure(state='disabled')
        self.status.set('Operación en curso…')
        def worker():
            try:
                self.events.put((True, work(), success))
            except Exception as exc:
                self.events.put((False, safe_error(exc), None))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            ok, result, success = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for control in self.controls:
                control.configure(state='readonly' if isinstance(control, ttk.Combobox) else 'normal')
            if ok:
                try:
                    success(result)
                except Exception as exc:
                    self.status.set(safe_error(exc))
            else:
                self.status.set(result)
            self.refresh()
        if not self.closed:
            self.poll_after = self.root.after(100, self._poll)

    def begin_auth(self):
        key, secret = self.api_key.get().strip(), self.secret.get().strip()
        if not key or not secret:
            messagebox.showinfo('Faltan las claves', 'Introduce aquí tu API key y tu secreto de aplicación Last.fm. No necesitas compartirlos por chat.', parent=self.root)
            return
        self.token = None
        def complete(result):
            self.token = (result[0], key, secret)
            opened = webbrowser.open(result[1])
            self.status.set('Autoriza la aplicación en el navegador y pulsa «2. Ya he autorizado».' if opened else 'No se pudo abrir el navegador. Comprueba tu navegador predeterminado y vuelve a autorizar.')
        self._job(lambda: engine.Client(key, secret).begin_auth(), complete)

    def finish_auth(self):
        if not self.token:
            messagebox.showinfo('Autorización', 'Pulsa primero «1. Autorizar en Last.fm» y permite el acceso en el navegador.', parent=self.root)
            return
        token, key, secret = self.token
        def complete(result):
            name, session = result
            settings = dict(self.settings)
            # Sessions are tied to the application key that issued them.
            sessions = dict(settings.get('sessions', {})) if settings.get('api_key') == key else {}
            sessions[engine.account_id(name)] = session
            settings.update(api_key=key, secret=secret, sessions=sessions, account=name)
            self.vault.save(settings)
            self.settings = settings
            self.token = None
            self.account.set(name)
            self.status.set(f'Cuenta {name} autorizada. Revisa las escuchas antes de enviarlas.')
        self._job(lambda: engine.Client(key, secret).finish_auth(token), complete)

    def import_log(self):
        try:
            account = self.current_account()
        except ValueError:
            messagebox.showinfo('Cuenta', 'Introduce la cuenta a la que pertenecerán estas escuchas.', parent=self.root)
            return
        path = filedialog.askopenfilename(parent=self.root, title='Selecciona el registro exportado por el reproductor',
                 filetypes=[('Registros de escuchas', '*.log'), ('Todos los archivos', '*.*')])
        if not path:
            return
        def work():
            ledger = engine.Ledger(self.directory)
            try:
                return ledger.import_file(Path(path), account)
            finally:
                ledger.close()
        self._job(work, lambda result: self.status.set(f'Importación: {result.added} nuevas, {result.duplicates} repetidas, {result.upgraded} completadas. Copia local conservada.'))

    def sync(self):
        try:
            account, session = account_session(self.settings, self.current_account())
        except ValueError:
            messagebox.showinfo('Autoriza esta cuenta', 'Conecta y autoriza la cuenta seleccionada antes de enviar.', parent=self.root)
            return
        key, secret = self.settings.get('api_key', ''), self.settings.get('secret', '')
        def work():
            ledger = engine.Ledger(self.directory)
            try:
                return engine.SyncEngine(ledger, engine.Client(key, secret), account, session).sync()
            finally:
                ledger.close()
        self._job(work, lambda result: self.status.set(f'Lote procesado: {result["submitted"]} escuchas. Revisa los estados; otro lote requiere otro clic.'))

    def selected(self, allowed):
        ids = [int(item) for item in self.tree.selection()]
        if not ids or any(self.row_data[str(item)]['status'] not in allowed for item in ids):
            messagebox.showinfo('Selecciona las filas', 'Selecciona únicamente filas del estado adecuado para esta operación.', parent=self.root)
            return []
        return ids

    def confirm_timezone(self):
        ids = self.selected({'review'})
        if not ids:
            return
        offset = simpledialog.askinteger('Zona horaria del reproductor',
            'Desfase del reloj del reproductor respecto a UTC, en minutos.\nEjemplo: UTC+1 = 60; UTC+2 = 120.\nUsa el desfase de la fecha de esas escuchas, incluido el horario de verano.',
            parent=self.root, minvalue=-840, maxvalue=840)
        if offset is None:
            return
        self.local_change(lambda ledger, account: ledger.confirm_timezone(account, ids, offset), 'Zona confirmada. Las filas válidas ya están pendientes de envío.')

    def resolve(self, decision):
        ids = self.selected({'uncertain'})
        if not ids:
            return
        text = ('Permitir otro intento puede duplicar estas escuchas si Last.fm ya las recibió.\nComprueba antes tu historial. ¿Permitir su reenvío con un próximo clic?' if decision == 'pending'
                else 'Esta decisión es manual y no se verifica en Last.fm. ¿Aplicarla a las filas seleccionadas?')
        if messagebox.askyesno('Resolver envío sin confirmar', text, parent=self.root):
            self.local_change(lambda ledger, account: ledger.resolve_uncertain(account, ids, decision), 'Decisión guardada. No se ha enviado nada.')

    def local_change(self, operation, message):
        try:
            ledger = engine.Ledger(self.directory)
            try:
                ledger.backup()
                operation(ledger, self.current_account())
            finally:
                ledger.close()
            self.status.set(message)
        except Exception as exc:
            self.status.set(safe_error(exc))
        self.refresh()

    def backup(self):
        def work():
            ledger = engine.Ledger(self.directory)
            try:
                return ledger.backup()
            finally:
                ledger.close()
        self._job(work, lambda result: self.status.set('Copia de seguridad guardada en la carpeta local backups.'))

    def forget(self):
        if messagebox.askyesno('Olvidar credenciales', '¿Eliminar las claves y sesiones guardadas en este equipo?\nEl registro local de escuchas se conserva.', parent=self.root):
            try:
                self.vault.clear()
            except Exception as exc:
                self.status.set(safe_error(exc))
                return
            self.settings, self.token = {}, None
            self.api_key.set(''); self.secret.set('')
            self.status.set('Credenciales eliminadas de este equipo.')
            self.refresh()

    def close(self):
        if self.busy:
            messagebox.showinfo('Operación en curso', 'Espera a que termine la operación antes de cerrar. Un envío interrumpido necesita revisión manual.', parent=self.root)
            return
        self.closed = True
        self.token = None
        self.root.after_cancel(self.poll_after)
        self.root.destroy()


def run(directory=None, *, smoke=False):
    root = tk.Tk()
    app = App(root, directory or engine.default_data_dir())
    if smoke:
        root.after(500, app.close)
    root.mainloop()
    return 0
