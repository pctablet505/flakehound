# Security Policy

flakehound is a static-analysis CLI/pre-commit hook and pytest plugin: it parses
Python test files with `ast` and (from v0.2) writes run outcomes to a local
SQLite file. It never executes scanned code, makes network calls, or phones
home. Supported versions are the latest release on PyPI and the `main` branch;
please upgrade before reporting against an older version.

If you find a security issue — arbitrary code execution via a crafted test
file, a path-traversal in the config/history loader, or anything else that
breaks the "static scan only, no I/O beyond your repo" contract — please do
**not** open a public issue. Instead email **pctablet505@gmail.com** with a
description and, if possible, a minimal reproduction. We'll acknowledge within
a few days and aim to ship a fix or mitigation before any public disclosure.
