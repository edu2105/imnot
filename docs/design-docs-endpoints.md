# Design: Docs Endpoints

## Problem

README files are baked into the Docker image but not reachable over HTTP. Analysts
using AI-assisted tools (e.g. Cursor) inside a company network cannot point their
model at a running Mirage instance to get the docs without external GitHub access.

## Solution

Expose two read-only endpoints that serve the README files as plain text:

| Method | Path | File served |
|--------|------|-------------|
| `GET` | `/mirage/docs` | `README.md` |
| `GET` | `/mirage/docs/partners` | `partners/README.md` |

## Design decisions

- **No auth** — README content is not sensitive. Requiring `MIRAGE_ADMIN_KEY` would
  block the analyst use case (AI tools don't carry credentials by default).
- **Plain text response** — `Content-Type: text/plain; charset=utf-8`. AI tools consume
  raw markdown without issue; no HTML rendering needed.
- **Paths resolved relative to the package root** — `importlib.resources` or
  `pathlib.Path(__file__)` traversal, not hardcoded absolute paths, so it works both
  locally and inside the Docker image.
- **404 if file missing** — if a README is somehow absent (e.g. a stripped image),
  return `404` with a plain text message rather than a 500.
- **Not under `/mirage/admin/`** — docs are public, placing them under admin would
  imply they are protected and add unnecessary friction.

## Out of scope

- HTML rendering or syntax highlighting
- Any other files (CONTRIBUTING.md, CHANGELOG.md, etc.)
- Authentication / access control
- Versioned docs (always serves the docs for the running version)
