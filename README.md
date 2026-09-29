# The Ledger of Vanishing Tokens — Tellan

**Tellan** records and audits LLM API usage. It compares provider-reported token counts with local estimates, checks ledger integrity, and produces a reproducible statement for investigating discrepancies.

[![CI](https://github.com/cloudydreamland/TheLedgerOfVanishingTokens/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudydreamland/TheLedgerOfVanishingTokens/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![MIT license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Quick start

```bash
# From the repository root, after cloning:
python -m pip install .
# After the package is published to PyPI:
python -m pip install tellan

# Audit a ledger or supported provider export.
tellan audit usage.ledger

# Create a shareable Markdown and JSON statement.
tellan statement usage.ledger -o statement.md --json-out statement.json
```

To capture new OpenAI-compatible traffic through the local proxy:

```bash
tellan proxy --port 8317 --upstream https://api.example.com --ledger usage.ledger
```

Point your client at `http://127.0.0.1:8317/v1`. The default capture mode stores message counts, lengths, and short hashes rather than message text. Review the capture settings and ledger contents before sharing any artifact.

## What Tellan checks

- A hash-linked ledger detects accidental or post-capture edits to records.
- Local token counts are estimates or provider-specific counts; opaque tokenizers are reported as ranges or insufficient data.
- Reconciliation compares reported usage with the applicable estimate and price snapshot.
- A deterministic statement includes disputed records, anomalies, source hashes, and reproduction details.
- JSONL/CSV import supports documented New API and One API export formats.

## Security and accounting limits

The local hash chain is not a provider signature and does not prevent an operator with write access from rebuilding the chain. Tellan cannot observe requests that bypass its proxy or logs. Usage estimates can differ from provider billing because of hidden prompts, cache rules, batching, reasoning tokens, or tokenizer differences. A flagged discrepancy is a reason to investigate, not proof of overbilling.

## Documentation

- [中文文档](README.zh-CN.md)
- [One-page statement example](docs/statement_example.md)
- [New API / One API import notes](docs/newapi.md)
- [Tokenizer coverage and limits](docs/tiktoken.md)
- [Benchmark results](benchmarks/results.md)
- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)

## Development and security

See [CONTRIBUTING.md](CONTRIBUTING.md). Please report security issues privately; see [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
