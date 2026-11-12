"""Offline tests: synthetic logs and fake transports only."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from lastfm.engine import (APIError, Client, HTTPTransport, Ledger, SyncEngine, parse_log, signature)


NOW = 1794484800


def log(rows, tz="UTC"):
    return ("\ufeff#AUDIOSCROBBLER/1.1\n#TZ/" + tz + "\n" + "".join(rows)).encode("utf-8")


def row(timestamp=NOW-100, rating="L", artist="Björk", track="Jóga", duration=240):
    return f"{artist}\tHomogenic\t{track}\t1\t{duration}\t{rating}\t{timestamp}\t\n"


def response(entries):
    return {"scrobbles": {"@attr": {"accepted": str(sum(c == 0 for _, c in entries)),
                                    "ignored": str(sum(c != 0 for _, c in entries))},
            "scrobble": [{"timestamp": str(t), "ignoredMessage": {"code": str(c), "#text": ""}}
                         for t, c in entries]}}


class FakeTransport:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, params):
        self.calls.append(dict(params))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class ParserTests(unittest.TestCase):
    def test_utf8_bom_optional_field_and_partial_rows(self):
        entries = parse_log(log([row(), "broken\tline\n", row(NOW-50).rstrip("\n")]), now=NOW)
        self.assertEqual([e.status for e in entries], ["pending", "review", "review"])
        self.assertEqual(entries[0].artist, "Björk")
        self.assertIn("incompleta", entries[-1].reason)

    def test_unknown_zone_zero_future_invalid_utf8_and_skips_are_safe(self):
        unknown = parse_log(log([row(), row(0), row(rating="S")], tz="UNKNOWN"), now=NOW)
        self.assertEqual([e.status for e in unknown], ["review", "review", "ignored"])
        self.assertEqual(parse_log(log([row(NOW+1000)]), now=NOW)[0].status, "review")
        self.assertEqual(parse_log(log([row(duration=30)]), now=NOW)[0].status, "ignored")
        self.assertEqual(parse_log(log([row(artist="<UNTAGGED>")]), now=NOW)[0].status, "review")
        self.assertEqual(parse_log(b"#TZ/UTC\nA\xff\tB\tC\t1\t200\tL\t1794484000\t\n", now=NOW)[0].status, "review")

    def test_optional_mbid_column_can_be_absent(self):
        self.assertEqual(parse_log(log([row().rstrip("\t\n") + "\n"]), now=NOW)[0].status, "pending")

    def test_integer_overflow_and_non_decimal_values_stay_reviewable(self):
        for value in ["999999999999999999999999999999", "1_794_484_800", "not-a-date"]:
            entry = parse_log(log([row(timestamp=value)]), now=NOW)[0]
            self.assertEqual(entry.status, "review")
            self.assertLessEqual(entry.timestamp, 2**63-1)
        entry = parse_log(log([row(duration="9999999999999999999999999")]), now=NOW)[0]
        self.assertEqual(entry.status, "review")
        self.assertLessEqual(entry.duration, 2**63-1)


class LedgerFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / ".scrobbler.log"
        self.ledger = Ledger(self.base / "local")

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def import_rows(self, rows, account="alice", tz="UTC"):
        self.source.write_bytes(log(rows, tz))
        return self.ledger.import_file(self.source, account, now=NOW)


class LedgerTests(LedgerFixture):
    def test_dedup_preserves_separate_listens_accounts_and_source(self):
        original = log([row(), row(NOW-50), row()])
        self.source.write_bytes(original)
        result = self.ledger.import_file(self.source, "Alice", now=NOW)
        self.assertEqual((result.added, result.duplicates), (2, 1))
        again = self.ledger.import_file(self.source, "alice", now=NOW)
        self.assertEqual((again.added, again.duplicates), (0, 3))
        self.assertEqual(self.ledger.import_file(self.source, "bob", now=NOW).added, 2)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(Path(result.backup).read_bytes(), original)
        self.assertEqual(len(self.ledger.rows("ALICE")), 2)
        self.assertTrue(self.ledger.backup().is_file())

    def test_unknown_zone_requires_explicit_confirmation_and_keeps_dedup(self):
        self.import_rows([row(), row(0)], tz="UNKNOWN")
        first, timeless = self.ledger.rows("alice")
        self.ledger.confirm_timezone("alice", [first["id"]], offset_minutes=60, now=NOW)
        self.assertEqual(self.ledger.rows("alice")[0]["timestamp"], NOW-3700)
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "pending")
        self.assertEqual(self.ledger.rows("alice")[1]["status"], "review")
        self.assertEqual(self.ledger.import_file(self.source, "alice", now=NOW).added, 0)
        with self.assertRaises(ValueError):
            self.ledger.confirm_timezone("alice", [timeless["id"]], 0, now=NOW)

    def test_status_survives_restart_and_cross_account_changes_fail(self):
        self.import_rows([row()])
        ident = self.ledger.rows("alice")[0]["id"]
        with self.assertRaises(ValueError):
            self.ledger.resolve_uncertain("bob", [ident], "sent")
        self.ledger.close()
        self.ledger = Ledger(self.base / "local")
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "pending")

    def test_skipped_session_can_qualify_later_but_sent_or_uncertain_never_reset(self):
        self.import_rows([row(rating="S")])
        self.import_rows([row()])
        self.assertEqual(len(self.ledger.rows("alice")), 1)
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "pending")
        self.ledger.connection.execute("UPDATE entries SET status='sent'")
        self.ledger.connection.commit()
        self.import_rows([row(rating="S"), row()])
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "sent")
        self.ledger.connection.execute("UPDATE entries SET status='uncertain'")
        self.ledger.connection.commit()
        self.import_rows([row()])
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "uncertain")

    def test_completed_partial_row_can_enter_queue_on_reimport(self):
        self.source.write_bytes(log([row().rstrip("\n")]))
        self.ledger.import_file(self.source, "alice", now=NOW)
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "review")
        self.import_rows([row()])
        self.assertEqual(len(self.ledger.rows("alice")), 1)
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "pending")

    def test_oversized_numbers_can_be_archived_without_sqlite_overflow(self):
        self.import_rows([row(timestamp="9999999999999999999999999999999")])
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "review")

    def test_recover_interrupted_is_safe_and_does_not_touch_other_states(self):
        self.import_rows([row(), row(NOW-50)])
        self.ledger.connection.execute("UPDATE entries SET status='sending' WHERE id=1")
        self.ledger.connection.commit()
        with self.ledger.sync_lock():
            with self.assertRaises(RuntimeError):
                self.ledger.recover_interrupted()
        self.ledger.recover_interrupted()
        self.assertEqual([r["status"] for r in self.ledger.rows("alice")], ["uncertain", "pending"])


class APITests(unittest.TestCase):
    def test_ascii_signature_uses_raw_utf8_excludes_format_callback_and_signature(self):
        params = {"artist[1]": "Björk", "artist[10]": "X", "method": "track.scrobble",
                  "format": "json", "callback": "unused", "api_sig": "old"}
        expected = hashlib.md5("artist[10]Xartist[1]Björkmethodtrack.scrobblesecret".encode()).hexdigest()
        self.assertEqual(signature(params, "secret"), expected)

    def test_auth_modern_flow_does_not_request_password(self):
        transport = FakeTransport({"token": "dummy-token"}, {"session": {"name": "Alice", "key": "dummy-session"}})
        client = Client("dummy-key", "dummy-secret", transport)
        token, url = client.begin_auth()
        self.assertTrue(url.startswith("https://www.last.fm/api/auth/?"))
        self.assertEqual(client.finish_auth(token), ("Alice", "dummy-session"))
        self.assertEqual([c["method"] for c in transport.calls], ["auth.getToken", "auth.getSession"])
        self.assertNotIn("password", json.dumps(transport.calls))

    def test_transport_posts_utf8_form_only_to_https_endpoint(self):
        import io
        from urllib.parse import parse_qs

        class Opener:
            def open(self, req, timeout):
                self.req, self.timeout = req, timeout
                return io.BytesIO(b'{"token":"test-token"}')

        transport = HTTPTransport(timeout=7)
        transport.opener = opener = Opener()
        self.assertEqual(transport({"artist[0]": "Björk", "sk": "test-only"}), {"token": "test-token"})
        self.assertEqual(opener.req.full_url, "https://ws.audioscrobbler.com/2.0/")
        self.assertEqual(opener.req.method, "POST")
        self.assertEqual(opener.timeout, 7)
        self.assertEqual(parse_qs(opener.req.data.decode("ascii"))["artist[0]"], ["Björk"])
        self.assertNotIn("test-only", opener.req.full_url)


class SyncTests(LedgerFixture):
    def sync(self, transport, account="alice", maximum=50):
        client = Client("dummy-key", "dummy-secret", transport)
        return SyncEngine(self.ledger, client, account, "dummy-session").sync(maximum=maximum, now=NOW)

    def test_partial_acceptance_is_per_entry_and_does_not_resubmit(self):
        self.import_rows([row(), row(NOW-50), row(NOW-25, rating="S")])
        transport = FakeTransport(response([(NOW-100, 0), (NOW-50, 3)]))
        self.sync(transport)
        self.assertEqual([r["status"] for r in self.ledger.rows("alice")], ["sent", "ignored", "ignored"])
        self.sync(transport)
        self.assertEqual(len(transport.calls), 1)

    def test_timeout_after_send_is_uncertain_and_never_automatically_retried(self):
        self.import_rows([row()])
        transport = FakeTransport(TimeoutError("may have arrived"))
        self.sync(transport)
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "uncertain")
        self.sync(transport)
        self.assertEqual(len(transport.calls), 1)

    def test_truncated_or_inconsistent_responses_are_uncertain(self):
        for answer in [{}, response([]), response([(NOW-1, 0)]), {"scrobbles": {"scrobble": []}},
                       ValueError("truncated JSON"), {"error": 8, "message": "Operation failed"}]:
            with self.subTest(answer=answer):
                self.import_rows([row(NOW-100-len(self.ledger.rows("alice")))])
                self.sync(FakeTransport(answer))
                self.assertEqual(self.ledger.rows("alice")[-1]["status"], "uncertain")

    def test_explicit_rejected_errors_only_retry_on_next_explicit_sync(self):
        self.import_rows([row()])
        transport = FakeTransport({"error": 11, "message": "offline"}, response([(NOW-100, 0)]))
        self.sync(transport)
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "retry")
        self.assertEqual(len(transport.calls), 1)
        self.sync(transport)
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "sent")

    def test_rate_limit_and_individual_daily_or_future_limits_are_explicit_retries(self):
        self.import_rows([row(), row(NOW-50), row(NOW-25)])
        transport = FakeTransport({"error": 29, "message": "rate limited"},
                                  response([(NOW-100, 5), (NOW-50, 4), (NOW-25, 3)]),
                                  response([(NOW-100, 0), (NOW-50, 0)]))
        self.sync(transport)
        self.assertEqual([r["status"] for r in self.ledger.rows("alice")], ["retry", "retry", "retry"])
        self.assertEqual(len(transport.calls), 1)
        self.sync(transport)
        self.assertEqual([r["status"] for r in self.ledger.rows("alice")], ["retry", "retry", "ignored"])
        self.assertEqual(len(transport.calls), 2)
        self.sync(transport)
        self.assertEqual([r["status"] for r in self.ledger.rows("alice")], ["sent", "sent", "ignored"])

    def test_invalid_session_and_signature_rejected_without_loops(self):
        self.import_rows([row()])
        self.sync(FakeTransport({"error": 9, "message": "dummy-session dummy-secret"}))
        entry = self.ledger.rows("alice")[0]
        self.assertEqual(entry["status"], "auth_required")
        self.assertNotIn("dummy", entry["reason"])
        self.sync(FakeTransport({"error": 13, "message": "bad signature"}))
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "rejected")

    def test_batch_limit_order_and_interrupted_process_recovery(self):
        stamps = [NOW-1000+i for i in range(52)]
        self.import_rows([row(t) for t in reversed(stamps)])
        transport = FakeTransport(response([(t, 0) for t in stamps[:50]]))
        self.sync(transport)
        self.assertEqual(sum(r["status"] == "sent" for r in self.ledger.rows("alice")), 50)
        self.assertEqual(len([k for k in transport.calls[0] if k.startswith("artist[")]), 50)
        # Simulate a process dying after its durable pre-send transaction.
        self.ledger.connection.execute("UPDATE entries SET status='sending' WHERE status='pending'")
        self.ledger.connection.commit()
        self.sync(FakeTransport())
        self.assertEqual(sum(r["status"] == "uncertain" for r in self.ledger.rows("alice")), 2)

    def test_uncertain_resolution_needs_explicit_local_decision(self):
        self.import_rows([row()])
        self.sync(FakeTransport(TimeoutError()))
        ident = self.ledger.rows("alice")[0]["id"]
        self.ledger.resolve_uncertain("alice", [ident], "sent")
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "sent")
        with self.assertRaises(ValueError):
            self.ledger.resolve_uncertain("alice", [ident], "pending")

    def test_send_intent_is_durable_before_transport_and_crash_stays_uncertain(self):
        self.import_rows([row()])

        def crash(params):
            other = Ledger(self.ledger.directory)
            try:
                self.assertEqual(other.rows("alice")[0]["status"], "sending")
            finally:
                other.close()
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.sync(crash)
        self.ledger.recover_interrupted()
        self.sync(FakeTransport())
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "uncertain")

    def test_authorized_other_account_never_sends_first_accounts_queue(self):
        self.import_rows([row()], account="alice")
        self.sync(FakeTransport(), account="bob")
        self.assertEqual(self.ledger.rows("alice")[0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
