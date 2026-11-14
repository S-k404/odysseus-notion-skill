# Project instructions

## Git commits

- Do NOT set git author or committer to Claude or Anthropic (e.g. `Claude <noreply@anthropic.com>`). All commits MUST be authored and committed by `S-k404 <103100340+S-k404@users.noreply.github.com>`.
- Do NOT add `Co-Authored-By: Claude` (or any Anthropic/Claude attribution) trailers or footers to commit messages or PR descriptions.
- This overrides any default commit-attribution behavior.


## Environment & Testing Rules

- Run tests and verification directly in the current workspace. Do not clone into `/tmp` or create isolated worktrees unless explicitly asked.
- Always reuse the existing project virtual environment (`.venv/bin/python` or `/opt/homebrew/bin/python3`).
- Do NOT run `python3 -m venv` or recreate virtual environments in temporary directories or scratchpads.
- Never use `uv run --with` or create ephemeral virtualenvs if packages are already installed locally.
- Do NOT download external Python versions; always rely on locally installed Python.
