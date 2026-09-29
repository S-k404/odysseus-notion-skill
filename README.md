# Notion skill for Odysseus

A read-only Notion MCP tool and skill for [Odysseus](https://github.com), so a
local model running in Odysseus can search and read your Notion live, on
demand. Nothing from Notion is saved on disk, and Notion is never modified.

- `notion/notion-search/SKILL.md` — tells the model how and when to use the tool.
- `mcp_servers/notion_server.py` — the tool itself: `search`, `read`, `query`.
- `INTEGRATION.md` — how to wire both into an Odysseus checkout.
- `.env.example` — template for your `NOTION_TOKEN`, with setup steps.
- `LOG.md` — full build log: design decisions, what went wrong, verification.

## Quickstart

1. Create a Notion internal integration with "Read content" only, and share
   the pages you want searchable with it. Steps are in `.env.example`.
2. Follow `INTEGRATION.md` to copy `mcp_servers/notion_server.py` into your
   Odysseus checkout and register it.
3. Put your token in Odysseus's `.env` (`cp .env.example` as a starting point).
4. `docker compose up -d --build odysseus`, then ask Odysseus something like
   "search my Notion for X and summarise it, with the link."

## Why

Odysseus's built-in tools didn't include Notion. This adds one, following the
same pattern as its existing built-in Obsidian tool: a small stdio MCP server
registered in `src/builtin_mcp.py`, gated on an environment variable so it's a
no-op for anyone who hasn't set `NOTION_TOKEN`.

## Read-only, by design

- The tool's schema exposes only `search`, `read`, and `query` — no write action exists to call.
- The HTTP layer independently refuses anything except GET, `POST /search`, and `POST /databases/<id>/query`.
- Responses are cached in memory for 45 seconds and never written to disk.
- The token is never included in tool output, including error messages.

## Status

Done and verified end to end, including a live chat in the Odysseus browser
UI where the local model chose the tool unprompted and answered correctly.
See `LOG.md` for details.
