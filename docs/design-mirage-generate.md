# Design: `mirage generate` command

## Problem

Adding a new partner to Mirage requires knowing the directory convention
(`partners/{name}/partner.yaml`), writing valid YAML by hand, and restarting
or reloading the server. There is no guardrail between writing the file and
finding out it is invalid.

Generating partner YAML from API documentation (OpenAPI specs, Confluence pages,
PDFs, plain text) is inherently a semantic task — identifying which endpoints form
an async flow, which is an OAuth endpoint, which is a simple fetch — that cannot
be done reliably with a pure-code parser. The right tool for that step is an LLM.

---

## Decision

`mirage generate` is a **scaffolding and validation command**, not a parser or wizard.

- It takes an already-written (or LLM-generated) `partner.yaml` as input.
- It validates it using the same loader that runs at startup.
- It scaffolds the correct directory structure.
- It is designed to be called by Claude Code (or any LLM) as a verification and
  registration step in a larger workflow.

The generation of YAML content from API documentation is handled outside Mirage,
by Claude Code using `partners/README.md` as the authoring guide. Mirage only
validates and registers the result.

---

## Recommended workflow (human + Claude Code)

```
1. User shares API documentation with Claude Code
   (OpenAPI YAML, PDF, Confluence export, plain text — any format)

2. Claude reads partners/README.md to understand the YAML schema and pattern rules

3. Claude generates a partner.yaml and writes it to a temp location

4. Claude runs:
   mirage generate --dry-run --file /tmp/partner.yaml --json
   → Mirage validates and returns structured result (no files written)

5. If validation passes, Claude runs:
   mirage generate --file /tmp/partner.yaml
   → Mirage scaffolds partners/{name}/ and writes the file

6. Claude runs:
   POST /mirage/admin/reload
   → New partner's routes are live immediately, no restart needed
```

This workflow handles any input format and gets async pattern detection right
because the LLM understands semantics — something a code parser cannot do.

---

## Interface

### Modes

| Mode | Command | Purpose |
|---|---|---|
| Validate + scaffold | `mirage generate --file partner.yaml` | Primary use — registers a written YAML |
| Dry run | `mirage generate --dry-run --file partner.yaml` | Validate only, write nothing |
| JSON output | `mirage generate --file partner.yaml --json` | Machine-readable result for LLM consumption |
| Stdin | `mirage generate --file -` | Pipe-friendly (`cat partner.yaml \| mirage generate --file -`) |

### No wizard

An interactive wizard is explicitly out of scope:

- The `async` pattern has too many combinations to guide well through prompts
  (step count, ID delivery method, header names, body field names, etc.)
- Wizards block stdin and cannot be used by Claude Code or any LLM tool
- `partners/README.md` + Claude Code already provide a better guided experience
  for users who need help writing the YAML

---

## Output

### Human-readable (default)

```
Partner:     acme
Description: Acme Corp integration
Directory:   partners/acme/ (created)
File:        partners/acme/partner.yaml (written)

Consumer endpoints:
  POST    /acme/oauth/token            [oauth]
  GET     /acme/v1/reservations/{id}   [fetch]

Admin endpoints:
  POST    /mirage/admin/acme/reservation/payload
  GET     /mirage/admin/acme/reservation/payload
  POST    /mirage/admin/acme/reservation/payload/session
  GET     /mirage/admin/acme/reservation/payload/session/{session_id}

Run `mirage start` or call POST /mirage/admin/reload to activate.
```

### JSON (--json flag)

```json
{
  "status": "ok",
  "partner": "acme",
  "description": "Acme Corp integration",
  "directory": "partners/acme",
  "file": "partners/acme/partner.yaml",
  "created": true,
  "datapoints": [
    {
      "name": "token",
      "pattern": "oauth",
      "endpoints": [{ "method": "POST", "path": "/acme/oauth/token" }],
      "admin_routes": false
    },
    {
      "name": "reservation",
      "pattern": "fetch",
      "endpoints": [{ "method": "GET", "path": "/acme/v1/reservations/{id}" }],
      "admin_routes": true
    }
  ]
}
```

### Validation error (--json)

```json
{
  "status": "error",
  "error": "Datapoint 'token' uses pattern 'oauth' but has no POST endpoint."
}
```

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Validation error in the YAML |
| `2` | File conflict — `partners/{name}/partner.yaml` already exists (use `--force` to overwrite) |
| `3` | Partners directory not found |

---

## Flags

| Flag | Description |
|---|---|
| `--file PATH` | Path to `partner.yaml` to validate and register. Use `-` to read from stdin. |
| `--partners-dir PATH` | Partners directory (default: auto-discovered, same as `mirage start`) |
| `--dry-run` | Validate only — print what would happen, write nothing |
| `--json` | Output result as JSON (implies no interactive prompts) |
| `--force` | Overwrite `partners/{name}/partner.yaml` if it already exists |

---

## Implementation plan

### Files to create / modify

| File | Change |
|---|---|
| `mirage/cli.py` | Add `generate` command under the `cli` group |
| `tests/test_cli.py` | Add tests for generate: valid file, dry-run, conflict, invalid YAML, stdin |

No new modules required — the existing `load_partners()` loader handles validation.
The command is a thin CLI wrapper around the loader + filesystem operations.

### Logic (pseudocode)

```python
@cli.command()
@click.option("--file", "file_path", required=True)
@click.option("--partners-dir", default="partners")
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.option("--force", is_flag=True)
def generate(file_path, partners_dir, dry_run, json_output, force):
    # 1. Read YAML from file or stdin
    raw = read_input(file_path)

    # 2. Validate using existing loader (raises on error)
    partner = parse_and_validate(raw)

    # 3. Check for conflicts
    dest = resolve_partners_dir(partners_dir) / partner.name / "partner.yaml"
    if dest.exists() and not force:
        exit(2, conflict_message)

    # 4. If dry-run, print/return result without writing
    if dry_run:
        output_result(partner, created=False, json_output=json_output)
        return

    # 5. Scaffold and write
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(raw)

    # 6. Output result
    output_result(partner, created=True, json_output=json_output)
```

### Estimated scope

Small. The loader, validator, and directory logic already exist.
The command itself is ~100 lines including output formatting.

---

## Out of scope (this iteration)

| Item | Reason |
|---|---|
| Generating YAML from OpenAPI spec (pure code) | Semantic gap — can't detect async flows from endpoint structure alone |
| Built-in Claude API integration (`--from-spec`) | Redundant — Claude Code handles this natively; adds API key management complexity |
| Interactive wizard | Not LLM-compatible; `partners/README.md` + Claude Code is the better guided path |
| Updating an existing partner in place | Reload endpoint already handles this; out of scope for generate |

---

## Open questions

| # | Question | Status |
|---|----------|--------|
| 1 | Should `--dry-run` + `--json` be the standard pre-flight check Claude Code runs? | Leaning yes — makes the two-step (validate then register) explicit and safe |
| 2 | Should generate automatically call reload if the server is running? | Leaning no — keep concerns separate; user/Claude calls reload explicitly |
| 3 | Should `--file -` (stdin) be supported in the first iteration? | Leaning yes — trivial to add, enables pipe-friendly scripting |
