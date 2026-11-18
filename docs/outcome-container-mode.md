# Outcome: container mode

Goal: imnot is simple to run in an environment that scales, and several teams can use it.
Concrete target: a container platform such as Kubernetes — read-only root filesystem, no persistent
volume, partners baked into an image built from a contracts repo, logs on stdout, deployed by GitOps.

## What changes for the user

| Before (1.6.0) | After |
|---|---|
| `imnot start` always writes `imnot.db`, `imnot.toml`, `imnot.pid` and `logs/` | `--stateless` writes nothing: in-memory database, logs on stdout, no pid, no toml. A restart starts clean, and partners and seeded payloads are re-read |
| A broken `partner.yaml` is skipped and the server starts healthy with fewer partners | `--strict` exits 1 (same bar as `imnot validate`), so the rollout stops |
| `imnot validate` exits 0 when it finds no `partner.yaml` (for example a wrongly nested layout) | Exits 1 |
| Only `IMNOT_ADMIN_KEY` is read from the environment | Every `start` option has a variable: `IMNOT_PARTNERS_DIR`, `IMNOT_DB_PATH`, `IMNOT_BIND_HOST`, `IMNOT_BIND_PORT`, `IMNOT_BASE_URL` (new `--base-url`), `IMNOT_STATELESS`, `IMNOT_STRICT`. Flag > variable > `imnot.toml` > default |
| `POST`/`DELETE /imnot/admin/partners` answer 500 when `partners/` is read-only | 403 with the reason. In stateless mode they work in memory (see below) |
| The image runs as a named user and fixes host, db and partners dir in the `ENTRYPOINT` | Runs as uid/gid `10001`; the same defaults are `ENV` values, overridable one by one |
| A data directory the user cannot write fails with a traceback | One line saying which directory, which uid, and that `--stateless` needs none |

Also fixed, from the same review: a Load Test run in partner mode without `target_url` ended "done"
with 0 requests (now 422); a `validate:` rule on `body.` in a `paginated` endpoint always failed
(the handler now reads the body); a cursor issued by one datapoint was accepted by another (now 400).

Nothing changes unless a new option is used, with three exceptions, all listed under "Decisions":
`imnot validate` on an empty directory, the image's uid, and `IMNOT_PARTNERS_DIR` / `IMNOT_DB_PATH`
being read by a plain `imnot start` (before, only `--reload` used them internally).

## The UI stays fully usable in stateless mode

The admin UI exists so that people who do not write YAML can use every feature. Stateless mode must
not take that away; the only difference is that nothing survives a restart.

- `POST` and `DELETE /imnot/admin/partners` keep the partner in memory instead of writing a file. A
  save replaces the partner whole (old routes out, new ones in), so an edit applies without a reload.
- `GET /imnot/admin/partners/{name}` serves the in-memory YAML, so the Builder's pre-fill and its
  "fields would be dropped" guard work on partners made in the UI. `?format=yaml` downloads it: that
  is how a partner built in the UI gets into the partners repo.
- Reload goes back to the partners directory and drops what was changed over HTTP. The UI asks first.
- `/healthz` reports `stateless`; the UI shows a fixed banner and the footer names the mode.
- Rule for the classic mode: unchanged. Partners are written to disk, and a read-only directory is a
  403 with the reason. Memory is used only when `--stateless` was asked for, never as a silent fallback.

## Does it scale? One replica per instance

Stateless mode removes the volume, not the state. Everything imnot remembers lives in one process:

| With N replicas behind one Service | Why |
|---|---|
| Works: `oauth`, `static`, templating, `validate:`, `delay_ms`, `fail:` without `first_n` | No state |
| Works: `fetch` and `paginated` (`offset_limit`, `page_number`, `page_number_url`) served from `payloads/*.json` | Every replica seeds the same files |
| Breaks: payloads and sessions uploaded through the admin API | They land on one replica |
| Breaks: `polling` and `callback` (submit on one replica, poll or retrigger on another → 404) | Request ids are per process |
| Breaks: `cursor` pagination | Cursors are per process |
| Wrong counts: `fail.first_n`, `pending.times`, `rate_limit` | Each replica counts on its own (N times the limit) |
| Split: request journal, Load Test runs | Each replica has its own |

A shared SQLite file would not fix this (the counters and rate-limit buckets are in memory), and a
shared network store is a different product. It is also not needed: imnot is a mock, one process is
enough for a test environment, and start-up takes seconds.

**So "scale" means many small instances, not many replicas of one.** One Deployment with
`replicas: 1`, no autoscaler, `strategy: Recreate` (a rolling update would run two processes with
different state for a few seconds). Stateless mode is what makes that cheap: no volume, no
permissions, the same image everywhere, the whole configuration in environment variables.

## Several teams: one instance per team

| | One instance per team (recommended) | One shared instance |
|---|---|---|
| Route collisions | Impossible between teams | `ValueError` at start-up: one team's new route stops everybody's rollout |
| A broken partner under `--strict` | Stops that team's rollout only | Stops everybody's |
| Admin key | One per team | One for all: any team can replace another team's payloads |
| Journal (newest 1000), `fail.first_n`, `rate_limit` | Per team | Mixed and shared |
| Restart to pick up a contract change | Wipes that team's state | Wipes everybody's |
| Cost | One small pod per team | One pod |

Each team owns a contracts directory (`partners/<partner>/partner.yaml` plus `payloads/`), in its own
repo or in a folder of a shared one, and CI builds one image per team from the same imnot release:

```dockerfile
FROM ghcr.io/edu2105/imnot:<version>
COPY partners /app/partners
ENV IMNOT_STATELESS=1 IMNOT_STRICT=1
```

CI runs `imnot validate` before the build; `--strict` is the second net at start-up. A shared instance
stays possible for teams that agree to it (a path prefix per partner avoids collisions), but nothing in
imnot isolates them from each other.

## What was judged and left out

- **`/readyz`**: not needed. Seeding runs before the server accepts connections and `--strict` exits
  before that, so `GET /healthz` answering 200 already means "ready".
- **A shared store, multi-replica support**: see above.
- **Variables for log level, UI and page size**: `imnot.toml` covers them and can be copied into the
  image (`/app/imnot.toml`); it is read in stateless mode, only never created.
- **JSON logs, journal body redaction, sessions seeded from files, Helm chart, metrics**: useful, none
  blocks this goal. They stay in the plan as "later".

## Decisions left to the maintainer

1. **Image uid `10001`**: existing volumes and bind mounts written by older images belong to another
   uid; they need `chown -R 10001:10001` once (documented in `docs/deployment.md`). Alternative: keep
   the old uid and only make it numeric.
2. **`imnot validate` with no partners exits 1**: a fix for CI, but a change for anyone validating an
   empty directory on purpose.
3. **Require an admin key when binding to `0.0.0.0`**: today it is a warning. With one instance per team
   on a shared cluster it should arguably be an error, but that breaks current docker-compose setups
   that run without a key. Candidate for 2.0, or an opt-in flag now.
4. **Redact secrets in journal bodies**: only matters if real credentials reach the mock.
5. **Publish example Kubernetes manifests or a chart in this repo**: `docs/deployment.md` now has a
   minimal Deployment; a maintained chart is a bigger commitment.

## Done criteria

| # | Check | How |
|---|---|---|
| 1 | `imnot start --stateless --strict` starts from a read-only directory and creates no file | `tests/test_container_mode.py`; by hand in a `chmod 555` directory |
| 2 | `/healthz` is 200 and a `payloads/<datapoint>.json` is served without any upload | same |
| 3 | Log lines of `imnot.cli`, `imnot.http` and module loggers appear on stdout, once each | same |
| 4 | With a broken partner, `--strict` exits 1 and names the file; without `--strict` it is skipped as before | same |
| 5 | `imnot validate` on a directory with no `partner.yaml` exits 1 | `tests/test_cli.py` |
| 6 | Options come from the environment; flag > variable > toml; `IMNOT_PORT=tcp://…` (injected by Kubernetes for a Service named `imnot`) does not break start-up | `tests/test_container_mode.py` |
| 7 | In stateless mode a partner created or edited in the UI answers at once, writes no file, can be downloaded as YAML, and is gone after Reload (the UI warns) or a restart. Without stateless, an unwritable directory gives 403 | same; headless browser run by hand |
| 7b | The UI shows the stateless banner and footer only when `/healthz` says `"stateless": true` | `tests/test_ui.py`; headless browser run by hand |
| 8 | The image runs with `docker run --read-only --user 10001 -e IMNOT_STATELESS=1` and no volume or tmpfs; and without stateless it still works with a writable `/app/data` | by hand; CI `docker-smoke` |
| 9 | Without the new options, `imnot start` writes the same files as 1.6.0 | `test_default_start_still_writes_db_dir_files` and the existing suite |
| 10 | `tools/verify.sh` ends in `PASS` | — |
