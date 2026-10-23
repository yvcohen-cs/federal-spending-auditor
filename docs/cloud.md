# Codex Cloud reliability and reproducibility

Workstream A of [Issue #1](https://github.com/yvcohen-cs/federal-spending-auditor/issues/1).
Python 3.11 and 3.12 are supported and tested by GitHub Actions on Linux.
The repository's dependency ranges remain in `requirements.txt`; installations
are not pinned byte for byte. The offline smoke test has fixed synthetic inputs
and deterministic assertions, rather than byte-identical plots or timestamps.

## Setup and start

Select `yvcohen-cs/federal-spending-auditor` in Codex Cloud and a Python 3.11 or
3.12 runtime. Run these setup commands from the checkout root (not from a
Windows `.venv` copied into the cloud):

```sh
python --version
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

No background server or start service is needed. For each task/session, start
from the checkout root with:

```sh
export MPLBACKEND=Agg
export MPLCONFIGDIR="$(mktemp -d /tmp/auditor-mpl.XXXXXX)"
.venv/bin/python -m pytest -q
```

Use writable temporary storage for Matplotlib in cloud environments with a
read-only home directory. No API keys or local Windows services are required.
Preserve the cloud runtime's injected proxy variables and CA trust. Setup needs
package-index access; the tests need no live network once dependencies exist.
CI installs dependencies and runs `python -m pytest -q` for both Python versions.

## Explicit offline smoke test

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_federal_spending_auditor.py::test_pipeline_writes_cleaned_flagged_and_summary_outputs
```

This existing test injects mocked USAspending and FPDS clients into the complete
pipeline, checks record/flag counts and report content, and writes synthetic
outputs only under pytest's temporary directory. A successful run reports
`1 passed` and exits 0. It never calls the live endpoints. This is an explicit
test command; the production CLI still fails on live source errors and never
silently substitutes synthetic records. Run the full suite before review.

## Read-only connectivity diagnostic

```sh
.venv/bin/python -m src.network_diagnostic --timeout 5
```

The diagnostic makes one HEAD request to each official endpoint used by the
application: USAspending's `spending_by_award/` and FPDS's `ezsearch/FEEDS/ATOM`.
It does not POST queries, fetch datasets, read response bodies, follow redirects,
retry requests, or write reports. It prints JSON containing endpoint, local DNS
status, whether a proxy applies, HTTP status, and a sanitized error category.
Proxy addresses, credentials, exception messages, response headers and bodies
are omitted. TLS verification, configured CA bundles, proxy settings, and
`NO_PROXY` retain Requests' normal behavior; no insecure bypass is attempted.

DNS observation is bounded separately from the HTTP connect/read timeouts. These
are per-stage timeouts, not a strict total wall-clock deadline for Requests or
its platform resolver. Local DNS failure does not prevent a HEAD attempt because
the configured HTTP proxy can resolve the destination itself. No direct TCP
probe is used. Exit 0 means both HEAD responses were 2xx; exit 1 means at least
one request failed, redirected, or returned a non-2xx status; invalid arguments
exit 2. A 405 can mean a reachable endpoint does not support HEAD. A 403/429 may
come from a proxy or the remote service; HTTP status alone does not identify its
origin. A successful HEAD does not validate award-query access or data semantics.

When investigating restricted cloud access, inspect the current runtime policy
and allowlist `api.usaspending.gov` and `www.fpds.gov` through the supported cloud
configuration workflow if required. Do not edit proxy variables, disable TLS, or
follow redirects to bypass a restriction. The environment inspected for this
workstream reported an unrestricted HTTP policy in
`/etc/codex/network-policy.json`, with an inherited sidecar proxy; no allowlist
change was necessary. Policy and remote availability can change. An allowlisted
domain does not guarantee that the remote server accepts a request.

## Cloud and local workflow

The cloud checkout, Linux virtual environment, and test execution run independently
of a local Windows PC. Windows users can continue using the PowerShell commands
in the README. Exchange reviewed code through feature branches and pull requests;
recreate virtual environments independently on each machine. Existing production
CLI options and output locations are unchanged.

`data/*` and `reports/*` (except `.gitkeep`) are ignored, as are virtual
environments, `.env` variants and private key files. Ignore rules are a guardrail,
not a secret scanner: review `git diff --cached` before committing and never
force-add datasets, generated reports or credentials. Do not run production
collection as part of setup, CI, or the offline smoke test.
