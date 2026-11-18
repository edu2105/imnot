"""One X-Imnot-Session covering several datapoints, and the sessions primary-key migration."""

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from imnot.api.server import create_app
from imnot.engine.session_store import SessionStore

PARTNERS_DIR = Path(__file__).parent.parent / "partners"


def test_one_session_holds_payloads_for_several_datapoints(tmp_path):
    with TestClient(create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "s.db")) as c:
        sid = c.post("/imnot/admin/bookingco/charges/payload/session", json={"charges": [1]}).json()["session_id"]
        again = c.post(
            "/imnot/admin/staylink/report/payload/session",
            json={"report": "R1"},
            headers={"X-Imnot-Session": sid},
        ).json()["session_id"]
        assert again == sid
        h = {"X-Imnot-Session": sid}
        assert c.get("/bookingco/v1/charges", headers=h).json() == {"charges": [1]}
        assert c.get(f"/imnot/admin/staylink/report/payload/session/{sid}").json()["payload"] == {"report": "R1"}
        assert {s["datapoint"] for s in c.get("/imnot/admin/sessions").json() if s["session_id"] == sid} == {
            "charges",
            "report",
        }
        assert c.delete(f"/imnot/admin/sessions/{sid}").status_code == 200
        assert c.get("/imnot/admin/sessions").json() == []


def test_a_chosen_session_id_can_be_reused_and_replaced(tmp_path):
    with TestClient(create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "s.db")) as c:
        url = "/imnot/admin/bookingco/charges/payload/session"
        assert c.post(url + "?session=test-checkout-1", json={"v": 1}).json()["session_id"] == "test-checkout-1"
        c.post(url, json={"v": 2}, headers={"X-Imnot-Session": "test-checkout-1"})
        r = c.get("/bookingco/v1/charges", headers={"X-Imnot-Session": "test-checkout-1"})
        assert r.json() == {"v": 2}
        assert c.post(url, json={}, headers={"X-Imnot-Session": "bad id!"}).status_code == 400


def test_without_a_session_header_a_new_session_is_created_as_before(tmp_path):
    with TestClient(create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "s.db")) as c:
        url = "/imnot/admin/bookingco/charges/payload/session"
        assert c.post(url, json={"a": 1}).json()["session_id"] != c.post(url, json={"a": 2}).json()["session_id"]


def test_old_databases_are_migrated_without_losing_sessions(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, partner TEXT NOT NULL, datapoint TEXT NOT NULL, "
        "payload TEXT NOT NULL, created_at TEXT NOT NULL, last_used TEXT)"
    )
    conn.execute(
        "INSERT INTO sessions VALUES ('s-old', 'bookingco', 'charges', ?, '2026-01-01T00:00:00', NULL)",
        (json.dumps({"kept": True}),),
    )
    conn.commit()
    conn.close()

    store = SessionStore(db_path=db)
    store.init()
    assert store.resolve_payload("bookingco", "charges", "s-old") == {"kept": True}
    store.store_session_payload("staylink", "report", {"new": 1}, session_id="s-old")
    assert store.resolve_payload("staylink", "report", "s-old") == {"new": 1}
    pk = [r[1] for r in store._conn.execute("PRAGMA table_info(sessions)") if r[5]]
    assert pk == ["session_id", "partner", "datapoint"]
    store.close()

    again = SessionStore(db_path=db)  # a second start must not migrate (or fail) again
    again.init()
    assert again.resolve_payload("bookingco", "charges", "s-old") == {"kept": True}
    again.close()


def test_a_failed_migration_leaves_the_old_table_intact(tmp_path):
    """The INSERT fails mid-migration (a NULL the new schema rejects): nothing may be half-done."""
    import pytest

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, partner TEXT NOT NULL, datapoint TEXT NOT NULL, "
        "payload TEXT NOT NULL, created_at TEXT, last_used TEXT)"  # created_at nullable in this old copy
    )
    conn.execute("INSERT INTO sessions VALUES ('s-1', 'bookingco', 'charges', '{}', NULL, NULL)")
    conn.commit()
    conn.close()

    store = SessionStore(db_path=db)
    with pytest.raises(RuntimeError, match="left unchanged"):
        store.init()
    store.close()

    check = sqlite3.connect(db)
    tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    pk = [r[1] for r in check.execute("PRAGMA table_info(sessions)") if r[5]]
    rows = check.execute("SELECT session_id FROM sessions").fetchall()
    check.close()
    assert "sessions_v1" not in tables and pk == ["session_id"] and rows == [("s-1",)]
