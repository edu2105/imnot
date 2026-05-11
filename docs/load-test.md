# Load Test

imnot ships a built-in load testing tool under the **Load Test** tab in the Admin UI and the `/imnot/admin/stress/...` REST API. Use it to fire high-volume HTTP requests at a target URL and measure latency — no external tools required.

> **Security notice:** The stress endpoints fire outbound HTTP requests from the imnot server's IP. Never expose the admin port publicly without setting `IMNOT_ADMIN_KEY`. See the [Admin API reference](admin-api.md#load-test-endpoints) for details.

---

## Two modes

### Standalone

Fire any HTTP request at any URL. Useful for stress-testing your own infrastructure independent of any partner configuration.

**Fields:**
- **Target URL** — the endpoint to hit
- **Method** — POST, GET, PUT, PATCH, or DELETE
- **Headers** — optional JSON object merged with `Content-Type: application/json`
- **Payload Template** — JSON body; use `{{vary}}` as a placeholder for per-request variation
- **Vary Values** — one value per line, cycled in order across all requests
- **Rate / second** — target dispatch rate (1–2000)
- **Stop after** — total request count or duration in seconds

**Example — send 1 000 webhook events at 100/s, cycling through 5 property IDs:**

```
Target URL:       https://nifi.internal/webhook
Method:           POST
Payload Template: {"propertyId": "{{vary}}", "event": "checkin"}
Vary Values:      P001
                  P002
                  P003
                  P004
                  P005
Rate / second:    100
Stop after:       1000 requests
```

#### `{{vary}}` substitution

Place `{{vary}}` anywhere in the payload template. Each request replaces it with the next value from the Vary Values list, cycling when the list is exhausted:

- Request 1 → `P001`, Request 2 → `P002`, …, Request 6 → `P001` again

If Vary Values is empty, all requests receive the payload as-is.

---

### Partner-bound

Fire the global payload already uploaded for a `callback`-pattern partner/datapoint. Useful for replaying realistic production-shaped payloads at scale without writing them out again.

**Fields:**
- **Partner** — any partner with at least one `callback`-pattern datapoint (other patterns are excluded)
- **Datapoint** — the specific callback datapoint
- **Target URL** — where to send the payload (typically your NiFi endpoint)
- **Rate / second** and **Stop after** — same as standalone

The payload is fetched once from the session store at run start. If no global payload has been uploaded for the selected partner/datapoint, the run is rejected with a `422` before it starts.

Partner-bound mode does not support `{{vary}}` — the payload is sent as-is on every request.

---

## Live progress and results

After clicking **Run**, imnot returns a `run_id` immediately and fires requests in the background. The status bar updates every second:

```
Fired: 342 / 1000  |  Success: 338  |  Errors: 4  |  Elapsed: 3.4s
```

When the run completes (or is cancelled), the results panel shows:

| Metric | Description |
|--------|-------------|
| Fired | Requests that received any HTTP response |
| Success | 2xx responses |
| Errors | Non-2xx responses + timeouts + network failures |
| P50 / P95 / P99 | Latency percentiles in milliseconds |
| Actual rate/s | Measured throughput over the run duration |

Error counts are broken down by status code (`"500": 3`) plus `"timeout"` and `"network_error"` buckets.

> **Note:** A request is counted as "fired" only when a response is received (any HTTP status). If the target URL is unreachable, all requests land in `error_count` and `fired` stays 0.

---

## Templates

Save any standalone-mode configuration as a named template. Click **Save as Template** in the form, give it a name, and it appears at the top of the Load Test tab.

Templates are stored in the `imnot.db` database and persist across restarts. Apply a template to pre-fill the form; edit and re-save to update.

Templates are standalone-mode only — partner-bound configurations reference partner/datapoint names that may not exist on a different server.

---

## Run History

The last 50 completed runs are listed in the **Run History** table. From there you can:

- **View** — load the final results panel for any past run
- **Replay** — pre-fill the form with the exact configuration of a past run
- **Delete** — remove the run from history

Run history is stored in `imnot.db` and persists across restarts.

---

## REST API

All load test operations are also available over HTTP. See the [Admin API reference](admin-api.md#load-test-endpoints) for full request/response shapes.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/imnot/admin/stress/run` | Start a run |
| `GET` | `/imnot/admin/stress/{run_id}` | Poll progress / get results |
| `DELETE` | `/imnot/admin/stress/{run_id}` | Cancel a running job |
| `GET` | `/imnot/admin/stress/runs` | List last 50 completed runs |
| `DELETE` | `/imnot/admin/stress/runs/{run_id}` | Delete a run from history |
| `GET` | `/imnot/admin/stress/templates` | List saved templates |
| `POST` | `/imnot/admin/stress/templates` | Save a template |
| `DELETE` | `/imnot/admin/stress/templates/{template_id}` | Delete a template |
