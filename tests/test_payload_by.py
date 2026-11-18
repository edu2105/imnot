"""fetch response.payload_by: one payload entry per path parameter value."""

import pytest
from fastapi.testclient import TestClient

from imnot.api.server import create_app
from imnot.loader.yaml_loader import parse_partner_yaml

_YAML = """\
partner: hotelco
datapoints:
  - name: reservation
    pattern: fetch
    endpoints:
      - method: GET
        path: {path}
        response:
          status: 200
          payload_by: {by}
"""


def _client(tmp_path, path="/hotelco/reservations/{id}", by="id", files=None):
    d = tmp_path / "partners" / "hotelco"
    d.mkdir(parents=True)
    (d / "partner.yaml").write_text(_YAML.format(path=path, by=by))
    for name, text in (files or {}).items():
        (d / "payloads").mkdir(exist_ok=True)
        (d / "payloads" / name).write_text(text)
    return TestClient(create_app(partners_dir=tmp_path / "partners", db_path=tmp_path / "b.db"))


def test_each_id_gets_its_own_entry(tmp_path):
    with _client(tmp_path) as c:
        c.post("/imnot/admin/hotelco/reservation/payload", json={"R1": {"guest": "Ana"}, "R2": {"guest": "Leo"}})
        assert c.get("/hotelco/reservations/R1").json() == {"guest": "Ana"}
        assert c.get("/hotelco/reservations/R2").json() == {"guest": "Leo"}
        missing = c.get("/hotelco/reservations/R3")
    assert missing.status_code == 404 and "'R3'" in missing.json()["detail"]


def test_sessions_get_their_own_map(tmp_path):
    with _client(tmp_path) as c:
        c.post("/imnot/admin/hotelco/reservation/payload", json={"R1": {"from": "global"}})
        sid = c.post("/imnot/admin/hotelco/reservation/payload/session", json={"R1": {"from": "session"}}).json()[
            "session_id"
        ]
        assert c.get("/hotelco/reservations/R1", headers={"X-Imnot-Session": sid}).json() == {"from": "session"}
        assert c.get("/hotelco/reservations/R1").json() == {"from": "global"}


def test_works_with_payload_files_and_other_param_names(tmp_path):
    files = {"reservation.json": '{"P-9": {"rooms": 3}}'}
    with _client(tmp_path, path="/hotelco/properties/{property_id}/reservation", by="property_id", files=files) as c:
        assert c.get("/hotelco/properties/P-9/reservation").json() == {"rooms": 3}


def test_non_object_upload_is_rejected(tmp_path):
    with _client(tmp_path) as c:
        up = c.post("/imnot/admin/hotelco/reservation/payload", json=[{"id": "R1"}])
        session_up = c.post("/imnot/admin/hotelco/reservation/payload/session", json=["x"])
    assert up.status_code == 422 and "payload_by" in up.json()["detail"]
    assert session_up.status_code == 422


def test_non_object_payload_file_is_422_on_get(tmp_path):
    with _client(tmp_path, files={"reservation.json": '[{"id": "R1"}]'}) as c:
        r = c.get("/hotelco/reservations/R1")
    assert r.status_code == 422 and "payload_by" in r.json()["detail"]


@pytest.mark.parametrize("path, by", [("/hotelco/reservations", "id"), ("/hotelco/reservations/{id}", "code")])
def test_payload_by_must_name_a_path_parameter(path, by):
    with pytest.raises(ValueError, match="must name a path parameter"):
        parse_partner_yaml(_YAML.format(path=path, by=by))
