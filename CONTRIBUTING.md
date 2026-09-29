# Contributing to The Ledger of Vanishing Tokens (tellan)

Thanks for considering a contribution. Please open an issue for a bug or a substantial change so the scope can be agreed before implementation. Small, focused pull requests with a clear before/after description are easiest to review.

## Development setup

Use Python 3.10 or newer. From the repository root:

```bash
python -m venv .venv
# Activate the environment, then:
python -m pip install -e ".[dev]"
pytest -q
ruff check src tests tools
```

Keep runtime dependencies optional unless the feature needs them. Update user documentation and the changelog when behavior or CLI options change. Add examples that are safe to copy and never include real credentials, personal information, or customer data.

## Review checklist

- The change matches the project's documented scope and limitations.
- Public API and output changes are documented.
- Evaluation claims include data source, sample scope, and a reproduction command.
- All required checks in `.github/workflows/` pass.

By contributing, you agree that your contribution is distributed under the project's MIT license.
