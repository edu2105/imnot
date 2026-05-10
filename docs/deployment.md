# Deployment Guide

---

## Docker

Use Docker when you want to run imnot as a persistent background service — on a shared dev server, in CI, or alongside other containers. For local development, the local install is simpler.

A pre-built image is published at `ghcr.io/edu2105/imnot:latest`. To use it without building locally:

```yaml
image: ghcr.io/edu2105/imnot:latest
```

The `partners/` directory and `data/` (SQLite db) are volume-mounted — partners can be added without rebuilding the image, and state persists across restarts.

```bash
docker compose up                   # start
docker compose restart              # reload after adding a partner YAML
docker compose down                 # stop (data persists in ./data/)
docker compose down -v              # stop and wipe all state
```

The container binds to `127.0.0.1` by default. To expose it on the network:

```yaml
ports:
  - "0.0.0.0:8000:8000"
environment:
  IMNOT_ADMIN_KEY: "your-secret-key"
```

---

## Cloud / Kubernetes

The published Docker image runs on any container platform. What imnot requires, regardless of provider:

- **Persistent storage** — mount a volume at `/app/data` so the SQLite database survives container restarts. Without it, all session state is lost on redeploy.
- **Admin key** — set `IMNOT_ADMIN_KEY` via environment variable. Required for any deployment reachable outside localhost.
- **Host binding** — pass `--host 0.0.0.0` as the start command so the container port is reachable from outside. The default `127.0.0.1` binding blocks external traffic.
- **Partner YAMLs** — either commit them to the repo (included in the image build) or mount a volume at `/app/partners` to manage them independently.
- **Health checks** — use `GET /healthz` for liveness and readiness probes. It always returns `200 {"status":"ok","version":"…"}` with no auth and no I/O.

---

## Adding a new partner

### From the CLI (local / development)

Use `imnot generate` to validate and scaffold a partner YAML in one step:

```bash
# Write your partner.yaml (see partners/README.md for the schema), then:
imnot generate --file /path/to/partner.yaml

# Dry-run first to validate without writing anything:
imnot generate --dry-run --file /path/to/partner.yaml --json
```

`imnot generate` validates the YAML, creates `partners/<name>/` if needed, writes the file, and prints a summary of all consumer and admin endpoints.

**With `--reload`:** the server picks up the new file and restarts automatically.

**Without `--reload`:** call `POST /imnot/admin/reload` or restart `imnot start`.

### Over HTTP (containerised deployment)

When imnot runs as a container, use `POST /imnot/admin/partners` to register a new partner without exec-ing into the container:

```bash
curl -X POST http://localhost:8000/imnot/admin/partners \
     -H "Authorization: Bearer $IMNOT_ADMIN_KEY" \
     --data-binary @/path/to/partner.yaml

# Overwrite an existing partner definition:
curl -X POST "http://localhost:8000/imnot/admin/partners?force=true" \
     -H "Authorization: Bearer $IMNOT_ADMIN_KEY" \
     --data-binary @/path/to/partner.yaml
```

`imnot generate` and `POST /imnot/admin/partners` use identical validation — both write the same `partners/<name>/partner.yaml` and produce the same result shape.

### Directory structure

```
partners/
└── mypartner/
    ├── partner.yaml
    └── payloads/       # optional example payload files
```
