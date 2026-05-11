from __future__ import annotations

import asyncio
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from imnot.engine.session_store import SessionStore
from imnot.engine.stress import StressStore, _active_runs, _new_id, run_stress

logger = logging.getLogger(__name__)


def register_stress_routes(app: FastAPI, store: SessionStore, stress_store: StressStore) -> None:
    async def start_run(request: Request) -> JSONResponse:
        try:
            config: dict = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})

        mode = config.get("mode", "standalone")
        total_count = config.get("total_count")
        duration_seconds = config.get("duration_seconds")

        if (total_count is None) == (duration_seconds is None):
            return JSONResponse(
                status_code=422,
                content={"detail": "Exactly one of total_count or duration_seconds must be provided"},
            )

        rate = config.get("rate_per_second")
        if not rate or float(rate) <= 0:
            return JSONResponse(status_code=422, content={"detail": "rate_per_second must be a positive number"})

        if mode == "partner":
            partner = config.get("partner")
            datapoint = config.get("datapoint")
            if not partner or not datapoint:
                return JSONResponse(
                    status_code=422,
                    content={"detail": "partner and datapoint are required in partner mode"},
                )
            payload = store.resolve_payload(partner, datapoint, None)
            if payload is None:
                return JSONResponse(
                    status_code=422,
                    content={"detail": f"No global payload uploaded for {partner}/{datapoint}"},
                )
        else:
            target_url = config.get("target_url")
            if not target_url:
                return JSONResponse(status_code=422, content={"detail": "target_url is required in standalone mode"})

        run_id = _new_id()
        stress_store.create_run(run_id, config)
        asyncio.create_task(run_stress(run_id, config, store, stress_store))
        return JSONResponse(status_code=201, content={"run_id": run_id, "status": "pending"})

    async def list_runs(request: Request) -> JSONResponse:
        runs = stress_store.list_runs(limit=50)
        return JSONResponse(runs)

    async def list_templates(request: Request) -> JSONResponse:
        templates = stress_store.list_templates()
        return JSONResponse(templates)

    async def create_template(request: Request) -> JSONResponse:
        try:
            body: dict = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})

        name = body.get("name", "").strip()
        if not name:
            return JSONResponse(status_code=422, content={"detail": "name is required"})

        config = body.get("config")
        if config is None:
            return JSONResponse(status_code=422, content={"detail": "config is required"})

        template_id = _new_id()
        stress_store.create_template(template_id, name, config)
        tmpl = stress_store.get_template(template_id)
        return JSONResponse(
            status_code=201,
            content={"template_id": template_id, "name": name, "created_at": tmpl["created_at"]},
        )

    async def delete_template(template_id: str) -> JSONResponse:
        deleted = stress_store.delete_template(template_id)
        if not deleted:
            return JSONResponse(status_code=404, content={"detail": f"Template '{template_id}' not found"})
        return JSONResponse({"status": "ok", "template_id": template_id})

    async def delete_run_history(run_id: str) -> JSONResponse:
        if run_id in _active_runs:
            return JSONResponse(
                status_code=409,
                content={"detail": f"Run '{run_id}' is still active; cancel it first"},
            )
        deleted = stress_store.delete_run(run_id)
        if not deleted:
            return JSONResponse(status_code=404, content={"detail": f"Run '{run_id}' not found"})
        return JSONResponse({"status": "ok", "run_id": run_id})

    async def get_run(run_id: str) -> JSONResponse:
        state = _active_runs.get(run_id)
        if state is not None:
            elapsed = time.monotonic() - state.started_at
            return JSONResponse(
                {
                    "run_id": run_id,
                    "status": state.status,
                    "fired": state.fired,
                    "success_count": state.success_count,
                    "error_count": state.error_count,
                    "elapsed_seconds": round(elapsed, 3),
                    "error_breakdown": state.error_breakdown,
                }
            )

        row = stress_store.get_run(run_id)
        if row is None:
            return JSONResponse(status_code=404, content={"detail": f"Run '{run_id}' not found"})

        results = row.get("results") or {}
        return JSONResponse(
            {
                "run_id": row["run_id"],
                "status": row["status"],
                "fired": results.get("fired"),
                "success_count": results.get("success_count"),
                "error_count": results.get("error_count"),
                "elapsed_seconds": results.get("elapsed_seconds"),
                "p50_ms": results.get("p50_ms"),
                "p95_ms": results.get("p95_ms"),
                "p99_ms": results.get("p99_ms"),
                "actual_rate_per_second": results.get("actual_rate_per_second"),
                "duration_seconds": results.get("duration_seconds"),
                "error_breakdown": results.get("error_breakdown", {}),
            }
        )

    async def cancel_run(run_id: str) -> JSONResponse:
        state = _active_runs.get(run_id)
        if state is None:
            row = stress_store.get_run(run_id)
            if row is None:
                return JSONResponse(status_code=404, content={"detail": f"Run '{run_id}' not found"})
            return JSONResponse(status_code=409, content={"detail": f"Run '{run_id}' is already in terminal state"})

        if state.status in ("done", "cancelled", "error"):
            return JSONResponse(status_code=409, content={"detail": f"Run '{run_id}' is already in terminal state"})

        state.cancel_event.set()
        return JSONResponse({"status": "cancelled", "run_id": run_id})

    start_run.__name__ = "stress_start_run"
    list_runs.__name__ = "stress_list_runs"
    delete_run_history.__name__ = "stress_delete_run_history"
    list_templates.__name__ = "stress_list_templates"
    create_template.__name__ = "stress_create_template"
    delete_template.__name__ = "stress_delete_template"
    get_run.__name__ = "stress_get_run"
    cancel_run.__name__ = "stress_cancel_run"

    app.add_api_route("/imnot/admin/stress/run", start_run, methods=["POST"])
    app.add_api_route("/imnot/admin/stress/runs", list_runs, methods=["GET"])
    app.add_api_route("/imnot/admin/stress/runs/{run_id}", delete_run_history, methods=["DELETE"])
    app.add_api_route("/imnot/admin/stress/templates", list_templates, methods=["GET"])
    app.add_api_route("/imnot/admin/stress/templates", create_template, methods=["POST"])
    app.add_api_route("/imnot/admin/stress/templates/{template_id}", delete_template, methods=["DELETE"])
    app.add_api_route("/imnot/admin/stress/{run_id}", get_run, methods=["GET"])
    app.add_api_route("/imnot/admin/stress/{run_id}", cancel_run, methods=["DELETE"])

    logger.debug("Registered stress routes")
