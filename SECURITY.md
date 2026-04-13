# Security Policy

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, use GitHub's private vulnerability reporting feature:

1. Go to the [Security tab](../../security) of this repository
2. Click **"Report a vulnerability"**
3. Fill in the details — what you found, how to reproduce it, and the potential impact

You will receive a response within 5 business days. If the vulnerability is confirmed,
a fix will be prioritised and a CVE will be requested where appropriate.

## Scope

Mirage is an integration-testing mock server. While local use is the default, it can be
deployed for team or company-internal use — including cloud environments. The expected
deployment models are:

- **Local development** — bound to `127.0.0.1`, no authentication required
- **Shared / team deployment** — exposed within a private network or cloud environment,
  protected with `MIRAGE_ADMIN_KEY`

Reports are most valuable for vulnerabilities that affect deployments where Mirage is
accessible over a network (e.g. a shared staging environment or a cloud deployment).

## Supported Versions

Only the latest release is actively maintained.
