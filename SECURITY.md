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

Mirage is a local integration-testing mock server. It is not designed to be exposed to
the public internet. The expected deployment model is:

- **Local development** — bound to `127.0.0.1`, no authentication required
- **Shared / team deployment** — bound behind a private network, protected with
  `MIRAGE_ADMIN_KEY`

Reports are most valuable for vulnerabilities that affect deployments where Mirage is
accessible within a network (e.g. a team staging environment).

## Supported Versions

Only the latest release is actively maintained.
