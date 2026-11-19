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

### Upgrading from 1.6.0 or earlier: the image's user

The image now runs as the fixed numeric user `10001:10001` (before: a named system user with whatever uid the build assigned). A `data/` directory or volume written by an older image belongs to the old uid, and the container stops at start-up with `Cannot write logs to /app/data/logs`. Fix it once:

```bash
sudo chown -R 10001:10001 ./data          # bind mount
docker run --rm -u 0 -v <volume>:/app/data --entrypoint chown ghcr.io/edu2105/imnot:latest -R 10001:10001 /app/data   # named volume
```

The image's defaults are now environment variables instead of `ENTRYPOINT` flags (`IMNOT_BIND_HOST=0.0.0.0`, `IMNOT_DB_PATH=/app/data/imnot.db`, `IMNOT_PARTNERS_DIR=/app/partners`). The values are the same, and flags appended to `docker run <image> …` still win.

---

## Containers without storage: stateless mode

For Kubernetes and similar platforms, run imnot **stateless**: partners baked into the image, nothing written to disk, logs on stdout. Restarting the container rebuilds everything from the image.

```dockerfile
# Dockerfile in your contracts repo (partners/<partner>/partner.yaml, partners/<partner>/payloads/*.json)
FROM ghcr.io/edu2105/imnot:<version>
COPY partners /app/partners
ENV IMNOT_STATELESS=1 IMNOT_STRICT=1
```

```bash
docker run --read-only -e IMNOT_ADMIN_KEY=<secret> -p 8000:8000 <your-image>
```

- **`IMNOT_STATELESS=1`** (`--stateless`) — in-memory database, logs to stdout only, no `imnot.pid`, no `imnot.toml`, no volume and no writable directory needed. Payloads and sessions uploaded through the admin API work as usual and are gone after a restart; `payloads/<datapoint>.json` files are loaded again at every start. Partners created, edited or deleted from the admin UI or `POST`/`DELETE /imnot/admin/partners` work too, in memory: see [below](#changing-partners-on-a-stateless-server). `imnot stop`, `imnot status`, `imnot payload` and `imnot sessions` cannot reach an in-memory server: stop it with `SIGTERM` and use the admin API.
- **`IMNOT_STRICT=1`** (`--strict`) — start-up exits 1 unless every partner passes `imnot validate`. A completely empty partners directory passes (an instance whose partners are made in the UI); one with content but no `<partner>/partner.yaml` fails. Without it a broken `partner.yaml` is skipped and the container still reports healthy. Run `imnot validate --partners-dir partners` in the contracts repo's CI as well.
- **Configuration** — every `imnot start` option has an environment variable (see [cli.md](cli.md#environment-variables)). Set `IMNOT_BASE_URL` to the public URL if you use `page_number_url` pagination or the Postman export. Other settings go in an `imnot.toml` copied to `/app/imnot.toml`.
- **Admin key** — set `IMNOT_ADMIN_KEY` from a secret. Required for any deployment reachable outside localhost.
- **Health checks** — `GET /healthz` for liveness and readiness. It answers `200 {"status":"ok","version":"…"}` with no auth and no I/O, and only once partners are loaded and payload files seeded.

### Changing partners on a stateless server

The admin UI stays fully usable: the Builder creates and edits partners, and their routes answer at once. Nothing is written — the partner lives in memory, on top of the ones the image ships:

- A **restart** goes back to the image. So does **Reload** (`POST /imnot/admin/reload`): it re-reads the partners directory and drops every partner created, edited or deleted over HTTP. The UI asks before reloading.
- To **keep** a partner, download its YAML (the download button on its card, or `GET /imnot/admin/partners/<name>?format=yaml`) and commit it to your partners repo as `partners/<name>/partner.yaml`.
- The UI shows a "Stateless mode" banner, and `GET /healthz` reports `"stateless": true`.

Without `--stateless`, partners are written to the partners directory as before; if that directory is read-only the admin API answers `403` with the reason (it never falls back to memory on its own).

### One replica per instance, one instance per team

imnot keeps its state in one process (uploaded payloads, sessions, `polling` and `callback` request ids, cursors, `fail.first_n` and `pending` counters, rate-limit buckets, the request journal). Two replicas behind one Service do not share any of it: a `polling` submit answered by one replica gets a 404 from the other. Run **one replica** and do not autoscale it. To serve more teams, run more instances — each team with its own contracts image, admin key and journal — rather than a bigger shared one: on a shared instance a route collision or a broken partner under `--strict` stops every team's rollout.

### Several teams, one contracts repo

One repository can hold every team's partners, and still give each team its own instance:

```
imnot-contracts/
├── Dockerfile
├── CODEOWNERS                 # /teams/team-a/ @team-a-owners, /teams/team-b/ @team-b-owners
└── teams/
    ├── team-a/partners/<partner>/partner.yaml   (+ payloads/*.json)
    └── team-b/partners/<partner>/partner.yaml
```

```dockerfile
FROM ghcr.io/edu2105/imnot:<version>
ARG TEAM
COPY teams/${TEAM}/partners /app/partners
ENV IMNOT_STATELESS=1 IMNOT_STRICT=1 IMNOT_INSTANCE_NAME=${TEAM}
```

CI validates and builds one image per folder, for example with a GitHub Actions matrix:

```yaml
jobs:
  contracts:
    strategy:
      fail-fast: false               # team-a's broken partner does not stop team-b's image
      matrix:
        team: [team-a, team-b]       # or list teams/* in a previous job
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pipx run imnot validate --partners-dir teams/${{ matrix.team }}/partners
      - run: docker build --build-arg TEAM=${{ matrix.team }} -t registry.example.test/imnot-${{ matrix.team }}:${{ github.sha }} .
```

- **One instance and one admin key per team.** Each team deploys its own image with its own `IMNOT_ADMIN_KEY` secret. `IMNOT_INSTANCE_NAME` puts the team's name in the admin UI header, the browser tab and `/healthz`, so nobody edits the wrong one.
- **`CODEOWNERS` per folder**, so a team reviews changes to its own partners only.
- **Why not one shared instance?** Two teams defining the same route is a start-up error for everybody; under `--strict` one team's broken `partner.yaml` blocks every team's rollout; there is a single admin key, so any team can replace another's payloads; and the request journal, `fail.first_n` counters and rate limits are shared.

A minimal Kubernetes Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: imnot-team-a
spec:
  replicas: 1
  strategy:
    type: Recreate            # never two processes with different state
  selector:
    matchLabels: {app: imnot-team-a}
  template:
    metadata:
      labels: {app: imnot-team-a}
    spec:
      securityContext:
        runAsNonRoot: true    # the image's user is 10001:10001
      containers:
        - name: imnot
          image: registry.example.test/team-a/imnot-contracts:<git sha>
          ports: [{containerPort: 8000}]
          env:
            - name: IMNOT_ADMIN_KEY
              valueFrom: {secretKeyRef: {name: imnot-team-a, key: admin-key}}
            - name: IMNOT_BASE_URL
              value: https://imnot-team-a.example.test
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          readinessProbe: {httpGet: {path: /healthz, port: 8000}}
          livenessProbe: {httpGet: {path: /healthz, port: 8000}}
```

Kubernetes injects `IMNOT_PORT=tcp://…` into pods when a Service is called `imnot`. imnot does not read that variable (the port is `IMNOT_BIND_PORT`), so any Service name is safe.

### With a volume instead

If state must survive restarts, skip `IMNOT_STATELESS` and mount a volume at `/app/data` (writable by uid `10001`; in Kubernetes, `fsGroup: 10001`). The database, `imnot.toml` and `logs/` live there; set `[logging] stdout = true` in `/app/data/imnot.toml` to also get logs on the console. Still one replica: SQLite on a shared volume does not make replicas share counters or rate limits. Partner YAMLs can be baked into the image as above or mounted at `/app/partners`.

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

In stateless mode the partner is kept in memory instead of written (see [above](#changing-partners-on-a-stateless-server)). When `/app/partners` is read-only and the server is not stateless, this answers `403` with the reason.

`imnot generate` and `POST /imnot/admin/partners` use identical validation — both write the same `partners/<name>/partner.yaml` and produce the same result shape.

### Directory structure

```
partners/
└── mypartner/
    ├── partner.yaml
    └── payloads/       # optional example payload files
```
