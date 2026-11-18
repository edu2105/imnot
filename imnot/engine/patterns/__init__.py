"""Pattern handlers for mock endpoint behaviour, plus helpers they share."""

from __future__ import annotations

from fastapi.responses import JSONResponse


def no_payload_response(partner: str, datapoint: str, session_id: str | None) -> JSONResponse:
    """404 for a payload-backed route with nothing uploaded, with a hint on how to fix it.

    ``detail`` keeps its historical wording; ``hint`` tells the user exactly what to do, since a
    bare 404 here is easy to mistake for the partner's own 404.
    """
    if session_id:
        detail = f"No session payload found for session '{session_id}'"
        hint = (
            f"Create the session with POST /imnot/admin/{partner}/{datapoint}/payload/session "
            "and send its session_id in X-Imnot-Session"
        )
    else:
        detail = f"No global payload found for {partner}/{datapoint}"
        hint = (
            f"Upload one with POST /imnot/admin/{partner}/{datapoint}/payload (JSON body), "
            f"or add partners/{partner}/payloads/{datapoint}.json"
        )
    return JSONResponse(status_code=404, content={"detail": detail, "hint": hint}, headers={"X-Imnot-Hint": hint})
