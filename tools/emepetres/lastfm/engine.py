"""Read-only Rockbox log import and conservative, durable Last.fm submission.

No device discovery, card writes, automatic networking, or network retries.
All HTTP calls can be replaced by a callable for offline testing.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Callable
from urllib import error, parse, request
import uuid


API_URL = "https://ws.audioscrobbler.com/2.0/"
AUTH_URL = "https://www.last.fm/api/auth/"
STATES = ("pending", "sent", "ignored", "review", "uncertain", "retry",
          "auth_required", "rejected", "sending")


def account_id(value: str) -> str:
    value = value.strip().casefold()
    if not value or len(value) > 256 or any(ord(c) < 33 for c in value):
        raise ValueError("Introduce un nombre de cuenta Last.fm válido.")
    return value


def default_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "emepetres" / "Lastfm"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "emepetres-lastfm"


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class Entry:
    line: int
    artist: str = ""
    album: str = ""
    track: str = ""
    track_number: str = ""
    duration: int = 0
    rating: str = ""
    timestamp: int = 0
    mbid: str = ""
    timezone: str = "UNKNOWN"
    status: str = "review"
    reason: str = ""
    raw: str = ""


def parse_log(data: bytes, *, now: int | None = None) -> list[Entry]:
    """Parse only complete UTF-8 lines; never guess an unknown timezone/date."""
    now = int(time.time()) if now is None else now
    zone = "UNKNOWN"
    entries = []
    for number, raw_bytes in enumerate(data.splitlines(keepends=True), 1):
        if number == 1:
            raw_bytes = raw_bytes.removeprefix(b"\xef\xbb\xbf")
        complete = raw_bytes.endswith((b"\n", b"\r"))
        try:
            raw = raw_bytes.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError:
            entries.append(Entry(number, raw=raw_bytes.hex(), reason="UTF-8 no válido; revisar el original."))
            continue
        if raw.startswith("#TZ/"):
            zone = raw[4:].strip().upper()
        if not raw.strip() or raw.startswith("#"):
            continue
        entry = Entry(number, timezone=zone, raw=raw)
        fields = raw.split("\t")
        if len(fields) in (7, 8):
            (entry.artist, entry.album, entry.track, entry.track_number,
             duration, entry.rating, timestamp) = fields[:7]
            entry.mbid = fields[7] if len(fields) == 8 else ""
            try:
                if not duration.isascii() or not duration.isdecimal() or not timestamp.isascii() or not timestamp.isdecimal():
                    raise ValueError
                entry.duration = int(duration)
                entry.timestamp = int(timestamp)
                if entry.duration > 2**63-1 or entry.timestamp > 2**63-1:
                    raise ValueError
            except ValueError:
                # Keep exact invalid values in raw/archive, not SQLite INTEGER.
                entry.duration = entry.timestamp = 0
                entry.reason = "Duración o fecha no válida."
            else:
                if entry.rating == "S":
                    entry.status, entry.reason = "ignored", "Saltada (S); no se envía."
                elif entry.rating != "L":
                    entry.reason = "Marca de escucha desconocida; se necesita L o S."
                elif entry.duration <= 30:
                    entry.status, entry.reason = "ignored", "La pista debe durar más de 30 segundos."
                elif not entry.artist.strip() or not entry.track.strip() or entry.artist.strip() == "<UNTAGGED>":
                    entry.reason = "Faltan artista o título válidos; no se deducen del nombre de archivo."
                elif any(ord(c) < 32 for value in (entry.artist, entry.album, entry.track, entry.mbid) for c in value):
                    entry.reason = "Los metadatos contienen caracteres de control."
                elif entry.timestamp <= 0:
                    entry.reason = "Fecha desconocida (registro timeless); no se inventa una fecha."
                elif zone != "UTC":
                    entry.reason = "Zona horaria desconocida; confirma el desfase respecto a UTC."
                elif entry.timestamp > now + 300:
                    entry.reason = "Fecha futura; revisa el reloj del reproductor."
                else:
                    entry.status = "pending"
        else:
            entry.reason = "Fila malformada: se esperaban 7 u 8 campos separados por tabuladores."
        if not complete:
            entry.status, entry.reason = "review", "Última fila incompleta; vuelve a importar el registro cuando termine de escribirse."
        entries.append(entry)
    return entries


def fingerprint(entry: Entry, source: Path) -> str:
    if entry.timestamp > 0 and entry.artist and entry.track:
        identity = [entry.timestamp, entry.artist, entry.album, entry.track,
                    entry.track_number, entry.duration, entry.mbid]
    else:
        # Unknown timestamps cannot safely identify listens across different files.
        # Retain each source row separately in review, never as sendable listens.
        identity = [str(source.resolve()).casefold() if os.name == "nt" else str(source.resolve()),
                    entry.line, entry.raw]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass
class ImportResult:
    added: int
    duplicates: int
    backup: str
    upgraded: int = 0


class Ledger:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "listens.sqlite3"
        self.connection = sqlite3.connect(self.path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY, account TEXT NOT NULL, fingerprint TEXT NOT NULL,
                artist TEXT NOT NULL, album TEXT NOT NULL, track TEXT NOT NULL,
                track_number TEXT NOT NULL, duration INTEGER NOT NULL, rating TEXT NOT NULL,
                timestamp INTEGER NOT NULL, original_timestamp INTEGER NOT NULL,
                mbid TEXT NOT NULL, timezone TEXT NOT NULL, status TEXT NOT NULL,
                reason TEXT NOT NULL, source TEXT NOT NULL, line INTEGER NOT NULL,
                raw TEXT NOT NULL, imported_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                UNIQUE(account, fingerprint));
            CREATE INDEX IF NOT EXISTS queue ON entries(account, status, timestamp);
            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY, account TEXT NOT NULL, source TEXT NOT NULL,
                sha256 TEXT NOT NULL, archive TEXT NOT NULL, imported_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL, old_status TEXT NOT NULL,
                new_status TEXT NOT NULL, reason TEXT NOT NULL, at INTEGER NOT NULL);
            PRAGMA user_version=1;
        """)

    def close(self):
        self.connection.close()

    def backup(self) -> Path:
        folder = self.directory / "backups"
        folder.mkdir(exist_ok=True)
        destination = folder / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".sqlite3")
        with closing(sqlite3.connect(destination)) as target:
            self.connection.backup(target)
        return destination

    def import_file(self, source: Path, account: str, *, now: int | None = None) -> ImportResult:
        source = Path(source).resolve()
        account = account_id(account)
        now = int(time.time()) if now is None else now
        # The selected file is opened for reading only. The exact bytes go to a
        # content-addressed archive before any row is admitted to the ledger.
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        archive = self.directory / "imports" / (digest + ".log")
        if not archive.exists():
            atomic_write(archive, data)
        elif archive.read_bytes() != data:
            raise OSError("La copia local existente no coincide; importación cancelada.")
        self.backup()
        entries = parse_log(data, now=now)
        added = upgraded = 0
        with self.connection:
            self.connection.execute("INSERT INTO imports(account,source,sha256,archive,imported_at) VALUES(?,?,?,?,?)",
                                    (account, str(source), digest, str(archive), now))
            for entry in entries:
                values = asdict(entry)
                columns = ("artist", "album", "track", "track_number", "duration", "rating",
                           "timestamp", "mbid", "timezone", "status", "reason", "line", "raw")
                cursor = self.connection.execute(
                    "INSERT OR IGNORE INTO entries(account,fingerprint," + ",".join(columns) +
                    ",original_timestamp,source,imported_at,updated_at) VALUES(" + ",".join("?" for _ in range(19)) + ")",
                    (account, fingerprint(entry, source), *(values[c] for c in columns), entry.timestamp,
                     str(source), now, now))
                added += cursor.rowcount
                if not cursor.rowcount and entry.status in {"pending", "review"} and entry.rating == "L":
                    previous = self.connection.execute("SELECT * FROM entries WHERE account=? AND fingerprint=?",
                        (account, fingerprint(entry, source))).fetchone()
                    is_skip = previous["status"] == "ignored" and previous["rating"] == "S"
                    completed = previous["status"] == "review" and (
                        "incompleta" in previous["reason"] or entry.status == "pending")
                    if is_skip or completed:
                        self.connection.execute("UPDATE entries SET rating=?,timezone=?,raw=?,source=?,line=? WHERE id=?",
                            (entry.rating, entry.timezone, entry.raw, str(source), entry.line, previous["id"]))
                        self._transition(previous["id"], entry.status, entry.reason or "Escucha completada al reimportar.", now)
                        upgraded += 1
        return ImportResult(added, len(entries)-added, str(archive), upgraded)

    def rows(self, account: str, status: str | None = None):
        sql = "SELECT * FROM entries WHERE account=?"
        args = [account_id(account)]
        if status:
            if status not in STATES:
                raise ValueError("Estado desconocido.")
            sql += " AND status=?"
            args.append(status)
        return self.connection.execute(sql + " ORDER BY id", args).fetchall()

    def counts(self, account: str):
        return {row["status"]: row["n"] for row in self.connection.execute(
            "SELECT status,COUNT(*) AS n FROM entries WHERE account=? GROUP BY status", (account_id(account),))}

    def _transition(self, ident: int, state: str, reason: str, now: int):
        previous = self.connection.execute("SELECT status FROM entries WHERE id=?", (ident,)).fetchone()[0]
        self.connection.execute("UPDATE entries SET status=?,reason=?,updated_at=? WHERE id=?", (state, reason, now, ident))
        self.connection.execute("INSERT INTO events(entry_id,old_status,new_status,reason,at) VALUES(?,?,?,?,?)",
                                (ident, previous, state, reason, now))

    def _selected(self, account: str, identifiers, allowed):
        rows = []
        for ident in identifiers:
            row = self.connection.execute("SELECT * FROM entries WHERE id=? AND account=?", (ident, account_id(account))).fetchone()
            if row is None or row["status"] not in allowed:
                raise ValueError("La selección no pertenece a esta cuenta o ya cambió de estado.")
            rows.append(row)
        return rows

    def confirm_timezone(self, account: str, identifiers, offset_minutes: int, *, now: int | None = None):
        """offset = device local clock minus UTC. Never guesses DST or date."""
        if not isinstance(offset_minutes, int) or not -840 <= offset_minutes <= 840:
            raise ValueError("El desfase debe estar entre -840 y 840 minutos.")
        now = int(time.time()) if now is None else now
        with self.connection:
            for row in self._selected(account, identifiers, {"review"}):
                if row["timezone"] == "UTC" or "Zona horaria desconocida" not in row["reason"] or row["timestamp"] <= 0:
                    raise ValueError("Solo se puede confirmar la zona de una escucha válida con fecha conocida.")
                timestamp = row["original_timestamp"] - offset_minutes * 60
                if timestamp <= 0 or timestamp > now + 300:
                    raise ValueError("El desfase produce una fecha no válida o futura.")
                self.connection.execute("UPDATE entries SET timestamp=?,timezone='UTC' WHERE id=?", (timestamp, row["id"]))
                self._transition(row["id"], "pending", f"Zona confirmada manualmente: UTC{offset_minutes:+d} minutos.", now)

    def resolve_uncertain(self, account: str, identifiers, decision: str):
        if decision not in {"sent", "ignored", "pending"}:
            raise ValueError("Decisión no válida.")
        with self.connection:
            for row in self._selected(account, identifiers, {"uncertain"}):
                self._transition(row["id"], decision, "Resolución manual del usuario; no verificada por el programa.", int(time.time()))

    def recover_interrupted(self):
        """Call on GUI startup. A live sync holds the lock, so cannot be mistaken for a crash."""
        with self.sync_lock():
            with self.connection:
                for row in self.connection.execute("SELECT id FROM entries WHERE status='sending'").fetchall():
                    self._transition(row["id"], "uncertain", "La aplicación se interrumpió durante el envío; comprueba Last.fm antes de resolver.", int(time.time()))

    @contextmanager
    def sync_lock(self):
        """An OS-held lock survives neither crash nor process exit; lock file does."""
        path = self.directory / "sync.lock"
        with path.open("a+b") as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    raise RuntimeError("Otra ventana está sincronizando; espera a que termine.") from None
            else:
                import fcntl
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise RuntimeError("Otra ventana está sincronizando; espera a que termine.") from None
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)


def signature(params: dict, secret: str) -> str:
    text = "".join(str(key) + str(params[key]) for key in sorted(params)
                   if key not in {"format", "callback", "api_sig"}) + secret
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class APIError(Exception):
    def __init__(self, code: int):
        self.code = code
        # Do not retain or display server text: it might echo submitted secrets.
        super().__init__(f"Last.fm ha devuelto el código {code}.")


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect must never forward the session key to another endpoint.
        return None


class HTTPTransport:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.opener = request.build_opener(NoRedirect())

    def __call__(self, params: dict):
        body = parse.urlencode(params, encoding="utf-8").encode("ascii")
        req = request.Request(API_URL, data=body, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "emepetres-offline-lastfm/1.0"})
        try:
            response = self.opener.open(req, timeout=self.timeout)
        except error.HTTPError as exc:
            # Error bodies carry the authoritative Last.fm error code too.
            response = exc
        with response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Respuesta demasiado grande.")
        return json.loads(raw.decode("utf-8"))


class Client:
    def __init__(self, api_key: str, secret: str, transport: Callable | None = None):
        if not api_key or not secret:
            raise ValueError("Configura tu API key y tu secreto de aplicación Last.fm.")
        self.api_key = api_key
        self._secret = secret
        self.transport = transport if transport is not None else HTTPTransport()

    def call(self, method: str, **params):
        params.update(method=method, api_key=self.api_key)
        params["api_sig"] = signature(params, self._secret)
        params["format"] = "json"
        answer = self.transport(params)
        if not isinstance(answer, dict):
            raise ValueError("Respuesta no reconocida.")
        if "error" in answer:
            raise APIError(int(answer["error"]))
        return answer

    def begin_auth(self):
        token = self.call("auth.getToken")["token"]
        if not isinstance(token, str) or not token:
            raise ValueError("No se recibió un token válido.")
        return token, AUTH_URL + "?" + parse.urlencode({"api_key": self.api_key, "token": token})

    def finish_auth(self, token):
        session = self.call("auth.getSession", token=token)["session"]
        name, key = session["name"], session["key"]
        account_id(name)
        if not isinstance(key, str) or not key:
            raise ValueError("No se recibió una sesión válida.")
        return name, key

    def scrobble(self, rows, session_key):
        if not 1 <= len(rows) <= 50:
            raise ValueError("Last.fm admite entre 1 y 50 escuchas por petición.")
        params = {"sk": session_key}
        for i, row in enumerate(rows):
            for key, column in (("artist", "artist"), ("track", "track"), ("timestamp", "timestamp"),
                                ("album", "album"), ("duration", "duration"), ("mbid", "mbid")):
                if row[column] != "":
                    params[f"{key}[{i}]"] = str(row[column])
            if row["track_number"].isdigit() and int(row["track_number"]) > 0:
                params[f"trackNumber[{i}]"] = row["track_number"]
        return self.call("track.scrobble", **params)


def outcomes(answer: dict, rows) -> list[tuple[str, str]]:
    """Validate the entire response before recording any acceptance as certain."""
    scrobbles = answer["scrobbles"]
    items = scrobbles["scrobble"]
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or len(items) != len(rows):
        raise ValueError("Respuesta incompleta.")
    results = []
    accepted = 0
    for item, row in zip(items, rows):
        if int(item["timestamp"]) != row["timestamp"]:
            raise ValueError("La respuesta no coincide con el lote enviado.")
        message = item.get("ignoredMessage", item.get("ignoredmessage"))
        code = int(message["code"])
        if code < 0:
            raise ValueError("Código de resultado desconocido.")
        accepted += code == 0
        state = "sent" if code == 0 else "retry" if code in {4, 5} else "ignored"
        reason = ("Aceptada por Last.fm." if code == 0 else
                  "Last.fm rechazó esta fecha como futura (código 4); espera antes de otro envío explícito." if code == 4 else
                  "Last.fm rechazó por el límite diario (código 5); espera al siguiente día antes de otro envío explícito." if code == 5 else
                  f"Ignorada por Last.fm (código {code}).")
        results.append((state, reason))
    counts = scrobbles["@attr"]
    if int(counts["accepted"]) != accepted or int(counts["ignored"]) != len(rows)-accepted:
        raise ValueError("Los totales de la respuesta no coinciden.")
    return results


class SyncEngine:
    def __init__(self, ledger: Ledger, client: Client, account: str, session_key: str):
        self.ledger, self.client = ledger, client
        self.account, self._session_key = account_id(account), session_key
        if not session_key:
            raise ValueError("Autoriza primero tu cuenta Last.fm.")

    def sync(self, *, maximum=50, now: int | None = None):
        """One explicit click, one batch. Never auto-repeat a possibly sent batch."""
        if not 1 <= maximum <= 50:
            raise ValueError("El máximo de un lote es 50.")
        now = int(time.time()) if now is None else now
        ledger = self.ledger
        with ledger.sync_lock():
            with ledger.connection:
                for row in ledger.connection.execute("SELECT id FROM entries WHERE account=? AND status='sending'", (self.account,)).fetchall():
                    ledger._transition(row["id"], "uncertain", "La aplicación se interrumpió durante el envío; comprueba Last.fm antes de resolver.", now)
            ledger.backup()
            with ledger.connection:
                ledger.connection.execute("BEGIN IMMEDIATE")
                rows = ledger.connection.execute(
                    "SELECT * FROM entries WHERE account=? AND status IN ('pending','retry','auth_required') ORDER BY timestamp,id LIMIT ?",
                    (self.account, maximum)).fetchall()
                for row in rows:
                    ledger._transition(row["id"], "sending", "Lote preparado de forma duradera antes de enviar.", now)
            if not rows:
                return {"submitted": 0, "counts": ledger.counts(self.account)}
            try:
                answer = self.client.scrobble(rows, self._session_key)
                results = outcomes(answer, rows)
            except APIError as exc:
                if exc.code in {11, 16, 29}:
                    state = "retry"
                elif exc.code == 9:
                    state = "auth_required"
                elif exc.code in {2, 3, 4, 5, 6, 7, 10, 13, 26}:
                    state = "rejected"
                else:
                    state = "uncertain"
                results = [(state, f"Last.fm código {exc.code}; " +
                            ("reintento disponible mediante otro clic." if state == "retry" else
                             "vuelve a autorizar la cuenta." if state == "auth_required" else
                             "rechazo explícito; revisa la configuración." if state == "rejected" else
                             "resultado no confirmado; revisa tu historial antes de resolver."))] * len(rows)
            except Exception:
                # Includes timeout, TLS/connect/read failures and malformed JSON.
                # Transport phase is not reliably observable in urllib. Be safe.
                results = [("uncertain", "Sin respuesta completa confirmable; puede haberse recibido. No se reintentará automáticamente.")] * len(rows)
            with ledger.connection:
                for row, (state, reason) in zip(rows, results):
                    ledger._transition(row["id"], state, reason, int(time.time()))
            return {"submitted": len(rows), "counts": ledger.counts(self.account)}
