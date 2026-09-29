# Publishing The Ledger of Vanishing Tokens (`tellan`)

Status checked: 2026-09-29.

## Current state

- Public GitHub repository: https://github.com/cloudydreamland/TheLedgerOfVanishingTokens (default branch `main`). The project files are uploaded; CI and distribution-build workflows have passed.
- The package `tellan` has no project on PyPI as of this check. The repository's GitHub `pypi` environment exists, but PyPI Trusted Publisher registration has not been configured.
- Current package version: `0.1.0rc1` (a pre-release). Review `CHANGELOG.md` and decide the release stage before publishing.
- Upload used GitHub's Contents/Git Data API because Git smart-protocol connectivity failed. The local branch history and GitHub snapshot history are disconnected. **Do not run `git push`, `git push --force`, or the old bulk-publish instructions from this folder** until a history-reconciliation plan is reviewed. Preserve the remote branch and tags during any migration.

## Configure first publication

Sign in to the PyPI account that should own this package, then open [PyPI account publishing settings](https://pypi.org/manage/account/publishing/). Since the package has not been created yet, add a pending GitHub Actions publisher with these values:

| Field | Value |
|---|---|
| PyPI project name | `tellan` |
| Owner | `cloudydreamland` |
| Repository | `TheLedgerOfVanishingTokens` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

PyPI creates a new project the first time a matching trusted workflow publishes it. The checked-in workflow runs only after a GitHub Release is published. Once the publisher is registered, update the package version and changelog if the current pre-release is not the intended first release; then create a matching tag and GitHub pre-release/release. Confirm the publish workflow succeeds and install the package in a clean environment. Do not upload manually with an API token.

This repository is configured for PyPI Trusted Publishing with OIDC (`id-token: write`); do not add a PyPI token to GitHub secrets. See [PyPI: creating a project with a Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) and [PyPA's publishing workflow guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).

## Local build commands

From this project directory, build and inspect distributions with:

    python -m pip install --upgrade build twine
    python -m build
    python -m twine check dist/*

The `Build distributions` GitHub Actions workflow already runs these checks on the published snapshot. A successful build does not itself publish a package.
