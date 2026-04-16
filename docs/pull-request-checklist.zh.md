# Pull Request Checklist

## Release Entry Docs

- `README.md`
- `docs/releases/v0.6.0.md`
- `USER_GUIDE.zh-CN.md`
- `packaging/offline/README.md`
- `v0.6.0`
- Windows
- `.zip`
- macOS / Linux
- `.tar.gz`

## Verification Profiles

- docs-only
- rules-only
- truth-only
- code-change
- `uv run ai-sdlc verify constraints`
- `python -m ai_sdlc program truth sync --dry-run`
- `uv run pytest`
- `uv run ruff check`
