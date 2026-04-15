# Contributing to imnot

Thanks for your interest in contributing. This document covers everything you need
to get started.

## How contributions work

imnot uses the standard GitHub fork model:

1. Fork the repository to your own account
2. Clone your fork and create a feature branch
3. Make your changes, add tests, and verify the full test suite passes
4. Open a pull request from your branch into `main` on this repo
5. CI runs automatically — all checks must pass before review
6. The maintainer reviews and merges

No one can push directly to `main`. All changes go through a PR with at least
one approving review and a passing CI run.

## Setting up locally

Requires Python 3.11 or later.

```bash
git clone https://github.com/<your-fork>/imnot.git
cd imnot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Running the tests

```bash
.venv/bin/pytest
```

All 228 tests should pass. The CI matrix runs on Python 3.11 and 3.12 — if you can,
test on both before opening a PR.

## Running the security scan

```bash
pip install bandit
bandit -r imnot/ -f screen
```

Expected output: 0 issues. Any new `# nosec` annotations must include an inline
explanation of why the finding is a false positive.

## What to work on

Check the [open issues](../../issues) for bugs and feature requests. Issues labelled
`good first issue` are a good starting point.

If you want to propose something new, open an issue first to discuss it before
writing code — this avoids duplicate effort and ensures the change fits the project's
direction.

## PR expectations

- One logical change per PR
- Tests for any new behaviour (aim for the same coverage level as the existing suite)
- No changes to `partners/README.md` or `CLAUDE.md` unless you are the maintainer
- Commit messages in the imperative: `fix: ...`, `feat: ...`, `chore: ...`

## AI-assisted contributions

We welcome contributions where AI tools help you write, review, or refactor code.
What we require is a human behind the wheel: someone who has read the codebase,
understands the change, and takes responsibility for what's submitted.

Fully autonomous submissions — PRs opened by an agent without a human reviewing
the change — will be closed without merge.

## Code style

- Python 3.11+ type annotations on all public functions
- `from __future__ import annotations` at the top of every module
- No external formatters enforced — just match the existing style

## Partner YAML authoring

See [`partners/README.md`](partners/README.md) for the full schema reference before
adding or modifying partner definitions.
