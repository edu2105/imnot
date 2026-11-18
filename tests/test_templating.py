"""Response templating: {{path.x}}, {{query.x}}, {{headers.x}}, {{body.a.b}}, {{request_id}}."""

import pytest
from fastapi.testclient import TestClient

from imnot.api.server import create_app
from imnot.engine.templating import has_placeholders, render

_CTX = {
    "path": {"id": "R1"},
    "query": {"lang": "es"},
    "headers": {"x-trace": "t-9"},
    "body": {"order": {"qty": 3, "items": [{"sku": "A"}]}},
    "request_id": "req-1",
}


@pytest.mark.parametrize(
    "template, expected",
    [
        ("{{path.id}}", "R1"),
        ("{{ path.id }}", "R1"),
        ("Reservation {{path.id}} ({{query.lang}})", "Reservation R1 (es)"),
        ("{{headers.X-Trace}}", "t-9"),
        ("{{body.order.qty}}", 3),
        ("{{body.order.items.0.sku}}", "A"),
        ("qty={{body.order.qty}}", "qty=3"),
        ("{{request_id}}", "req-1"),
        ("{{body.missing}}", None),
        ("x{{body.missing}}y", "xy"),
        ("{{vary}} and {{whatever}}", "{{vary}} and {{whatever}}"),
        (42, 42),
    ],
)
def test_render_values(template, expected):
    assert render(template, _CTX) == expected


def test_render_walks_dicts_and_lists_but_not_keys():
    assert render({"{{path.id}}": ["{{path.id}}", {"n": "{{body.order.qty}}"}]}, _CTX) == {
        "{{path.id}}": ["R1", {"n": 3}]
    }


def test_has_placeholders_ignores_unknown_roots():
    assert has_placeholders({"a": ["x {{path.id}}"]})
    assert not has_placeholders({"a": "{{vary}}", "b": 1})


def _client(tmp_path, yaml_text):
    d = tmp_path / "partners" / "tplco"
    d.mkdir(parents=True)
    (d / "partner.yaml").write_text(yaml_text)
    return TestClient(create_app(partners_dir=tmp_path / "partners", db_path=tmp_path / "t.db"))


def test_static_body_echoes_path_query_and_body(tmp_path):
    yaml_text = """\
partner: tplco
datapoints:
  - name: confirm
    pattern: static
    endpoints:
      - method: POST
        path: /tplco/bookings/{id}/confirm
        response:
          status: 200
          body:
            bookingId: "{{path.id}}"
            nights: "{{body.nights}}"
            message: "Confirmed {{path.id}} in {{query.lang}}"
"""
    with _client(tmp_path, yaml_text) as c:
        r = c.post("/tplco/bookings/B7/confirm?lang=es", json={"nights": 2})
    assert r.json() == {"bookingId": "B7", "nights": 2, "message": "Confirmed B7 in es"}


def test_polling_status_step_can_echo_the_id(tmp_path):
    yaml_text = """\
partner: tplco
datapoints:
  - name: job
    pattern: polling
    endpoints:
      - step: 1
        method: POST
        path: /tplco/jobs
        response: {status: 202, generates_id: true, id_body_field: jobId}
      - step: 2
        method: GET
        path: /tplco/jobs/{id}
        response:
          status: 200
          body: {jobId: "{{path.id}}", state: DONE}
"""
    with _client(tmp_path, yaml_text) as c:
        job_id = c.post("/tplco/jobs").json()["jobId"]
        assert c.get(f"/tplco/jobs/{job_id}").json() == {"jobId": job_id, "state": "DONE"}


@pytest.mark.asyncio
async def test_callback_payload_is_rendered_with_the_submit_request(monkeypatch):
    import imnot.engine.patterns.push as push

    sent = {}

    class FakeResponse:
        is_success = True
        status_code = 200

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, json=None, **kwargs):
            sent.update(method=method, url=url, json=json)
            return FakeResponse()

    class Store:
        def resolve_payload(self, partner, datapoint, session_id):
            return {"requestId": "{{request_id}}", "order": "{{body.orderId}}", "status": "OK"}

    monkeypatch.setattr(push.httpx, "AsyncClient", FakeClient)
    await push.fire_callback(
        Store(),
        "p",
        "d",
        None,
        "http://x/cb",
        "POST",
        context={"request_id": "push-1", "body": {"orderId": "O-5"}, "path": {}, "query": {}, "headers": {}},
    )
    assert sent["json"] == {"requestId": "push-1", "order": "O-5", "status": "OK"}


def test_callback_submit_hands_its_request_id_and_body_to_the_callback(tmp_path, monkeypatch):
    import imnot.engine.patterns.push as push

    captured = {}

    async def capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(push, "fire_callback", capture)
    yaml_text = """\
partner: tplco
datapoints:
  - name: notify
    pattern: callback
    endpoints:
      - method: POST
        path: /tplco/notify
        response: {status: 202, callback_url_field: callbackUrl}
"""
    with _client(tmp_path, yaml_text) as c:
        r = c.post("/tplco/notify", json={"callbackUrl": "http://x/cb", "orderId": "O-5"})
    assert captured["context"]["request_id"] == r.json()["request_id"]
    assert captured["context"]["body"]["orderId"] == "O-5"


def test_header_mode_callback_still_gets_the_submit_body(tmp_path, monkeypatch):
    import imnot.engine.patterns.push as push

    captured = {}

    async def capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(push, "fire_callback", capture)
    yaml_text = """\
partner: tplco
datapoints:
  - name: notify
    pattern: callback
    endpoints:
      - method: POST
        path: /tplco/notify
        response: {status: 202, callback_url_header: X-Callback-Url}
"""
    with _client(tmp_path, yaml_text) as c:
        c.post("/tplco/notify", json={"orderId": "O-5"}, headers={"X-Callback-Url": "http://x/cb"})
    assert captured["context"]["body"] == {"orderId": "O-5"}


def test_retrigger_renders_request_id(tmp_path, monkeypatch):
    import imnot.engine.patterns.push as push

    sent = []

    async def submit_capture(**kwargs):
        pass

    class FakeResponse:
        is_success = True
        status_code = 200

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, json=None, **kwargs):
            sent.append(json)
            return FakeResponse()

    monkeypatch.setattr(push, "fire_callback", submit_capture)  # the submit's own callback is not under test
    monkeypatch.setattr(push.httpx, "AsyncClient", FakeClient)
    yaml_text = """\
partner: tplco
datapoints:
  - name: notify
    pattern: callback
    endpoints:
      - method: POST
        path: /tplco/notify
        response: {status: 202, callback_url_field: callbackUrl}
"""
    with _client(tmp_path, yaml_text) as c:
        c.post("/imnot/admin/tplco/notify/payload", json={"requestId": "{{request_id}}"})
        rid = c.post("/tplco/notify", json={"callbackUrl": "http://x/cb"}).json()["request_id"]
        assert c.post(f"/imnot/admin/tplco/notify/callback/{rid}/retrigger").status_code == 200
    assert sent == [{"requestId": rid}]
