# Publishing The Ledger of Vanishing Tokens (`tellan`)

This guide prepares the existing local Git repository for its first public GitHub upload and documents the optional PyPI release. It does not publish automatically until the repository's PyPI Trusted Publisher is configured and a GitHub Release is published.

## Before creating the GitHub repository

1. Confirm the target GitHub owner and repository slug. README badges and package URLs currently use `cloudydreamland/TheLedgerOfVanishingTokens`; replace that owner consistently if your account differs.
2. Review `git status`, the full commit history, and tracked files for private material, credentials, local paths, and research artifacts that should not be public. Ignore rules prevent normal Git adds for local environments but do not remove files already tracked or secrets from history.
3. Review the current release version in `pyproject.toml`. The checked-in version is `0.1.0rc1`; do not publish an alpha/RC as stable unless that is intentional.
4. Create an empty public repository on GitHub. Do not initialize it with a README, license, or `.gitignore`; this folder already has its own Git history.

## Upload the existing repository

From this project directory, add the remote and push the current local branch as the remote default branch:

```bash
git remote add origin https://github.com/<GITHUB_OWNER>/tellan.git
git push -u origin HEAD:main
git push origin --tags
```

If `origin` is already configured, inspect it first and use `git remote set-url origin ...` only when you intend to change it. Confirm the files on GitHub, then check the Actions page for the CI and distribution-build workflows. In repository Settings, choose `main` as the default branch if GitHub has not done so.

Set the repository social preview to `.github/social-preview.png` under Settings → General → Social preview.

## Optional PyPI release

1. Check that the project name `tellan` is available and the account is ready to publish. Do not rely on a previous availability check.
2. On PyPI, configure Trusted Publishing for the GitHub owner, repository `tellan`, workflow `publish.yml`, and environment `pypi`.
3. From a clean environment, build and inspect the distributions:

   ```bash
   python -m pip install --upgrade build twine
   python -m build
   python -m twine check dist/*
   ```

4. Update the version and changelog, commit those changes, and create a matching tag such as `v0.1.0` only when the release is ready. Pre-release versions must use a matching pre-release tag.
5. Create and publish a GitHub Release for that tag. The `publish.yml` workflow will build and publish through PyPI Trusted Publishing.
6. Verify the uploaded wheel in a clean environment and confirm the README install command works.

Never put a PyPI API token or GitHub personal access token in the repository. See the [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/) for current Trusted Publishing details.

## Not done by this guide

Creating the GitHub repository, pushing history, configuring PyPI, and publishing a release remain user-controlled steps. The project contains an MIT license and a social preview card; review every tracked file before making the repository public.
