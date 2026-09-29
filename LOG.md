# Notion skill for Odysseus: build log

Date: 2026-09-29 to 2026-09-30
Status: DONE and verified end to end.

## Goal

Let Odysseus search and read the user's Notion live, so they can ask questions about it later. Nothing from Notion is saved on the computer, and Notion is never modified.

## Final result

- Odysseus has a read-only built-in tool, `manage_notion` (registered as "Built-in: Notion (read-only)").
- A skill, `notion-search` v2.0.0, tells the model how to use it.
- Every question searches Notion again; there is no export and no cache.

## What is where

| Item | Location |
| :--- | :--- |
| Skill (source copy) | `Odysseus Skill/notion/notion-search/SKILL.md` |
| Skill (installed) | `Odysseus/data/skills/notion/notion-search/SKILL.md` (has `owner: admin`, added by Odysseus) |
| Notion tool (new file) | `Odysseus/mcp_servers/notion_server.py` |
| Registration (edited) | `Odysseus/src/builtin_mcp.py`: `"notion"` entry, plus skip when `NOTION_TOKEN` is unset |
| Token pass-through (edited) | `Odysseus/docker-compose.yml`: `- NOTION_TOKEN=${NOTION_TOKEN:-}` |
| Token (edited by the user) | `Odysseus/.env`: `NOTION_TOKEN=...` (never read or printed by Claude) |

## How it works

`manage_notion` has three actions:

- `search`: finds pages and databases by title. Notion search matches titles only. An empty query lists the most recently edited items.
- `read`: returns a page's properties and text, or a database's columns and rows. Takes a Notion id or URL.
- `query`: returns the rows of a database, with an optional Notion filter.

Read-only is enforced twice. The tool exposes no write actions (the schema rejects anything else), and `_request()` refuses everything except GET, POST `/search` and POST `/databases/<id>/query`. Requests are paced at about 2.8 per second, 429 and 5xx responses are retried using Retry-After, and attachment links (pre-signed) are never shown. The token never appears in errors. Page text is labelled as untrusted data.

## What went wrong first, and why

1. Version 1.0 of the skill told the model to paste a Python helper into a `python` tool. Odysseus never sent that tool in the chat (its log listed web, memory, browser and Obsidian tools only), so the model said it had no Notion access.
2. Checked separately: the token reached the container and Notion answered HTTP 200. The connection was never the problem.
3. Also learned: Odysseus rewrites `SKILL.md` on save and only keeps multi-line text verbatim inside "When to Use", so code embedded in other sections would have been flattened.
4. Fix: replaced the Python helper with a proper MCP tool (same pattern as the existing Obsidian tool) and shortened the skill to instructions for that tool.

## Verification (2026-09-30)

- Offline tests against a fake Notion API (`check_server.py`, in the session scratchpad): search, read by URL, nested and paginated blocks, databases, filters, error handling, no token or signed URL leaks, and 7 write-style requests all blocked before any network call. Passed.
- Parser check: the installed skill loads and re-saves unchanged with Odysseus's own `skill_format.py`. Passed.
- Container rebuilt with `docker compose up -d --build odysseus`. Startup log: `MCP server connected: Built-in: Notion (read-only) (notion) - 1 tools via stdio`.
- Live test inside the container over real MCP, using the real token: tool list shows `manage_notion`; a live search returned 5 results; a live read of the first result succeeded (525 characters); an unknown or write-style action such as `create` is rejected by schema validation. Passed.

Not yet tested by Claude: the full chat flow (asking Odysseus a question in the browser and checking that its local model chooses the tool). That is the next thing to try.

## Upgrade: faster and better (2026-09-30)

Skill is now v2.1.0; `notion_server.py` was rewritten.

Speed:
- One pooled `httpx` client, so HTTPS connections are reused (2 connections instead of 11 in the test).
- Page trees are read level by level with children fetched in parallel, and the page's properties are fetched at the same time as its blocks.
- One shared rate limiter for all threads: sustained 2.8 requests/s (Notion's average limit is 3), bursts of up to 3, and a 429 slows every thread down.
- Successful reads and searches are cached in memory for 45 seconds (never on disk). `fresh=true` bypasses the cache. Errors are never cached, so a page you just shared works on the next try.
- Measured against a fake Notion API with 150 ms latency: reading a page with 9 sections took 3.0 s, versus about 5.6 s for the old one-request-at-a-time design. The remaining time is Notion's own rate limit.

Better results:
- Search also tries each keyword on its own (Notion only matches whole titles) and ranks the merged results by how many keywords the title contains, so one call does the work of several. Results are labelled page, row (with `in=` the database id) or database.
- `read` accepts `find=<words>` to return only the matching lines with context from a long page.
- Truncated database reads now say when more rows exist.

Efficiency:
- Default output cap lowered from 60,000 to 24,000 characters (about 6k tokens) so it fits a local model's context; `max_chars` raises it to 60,000.
- Ids in output are the short 32-character form; URLs and either id form are still accepted as input.
- Read depth is limited to 4 block levels, and a nested block Notion refuses no longer fails the whole read.

Verified with `check_server2.py` (real `mcp` and `httpx`, fake Notion server): ranking, caching, `find`, depth limit, database queries, retry after 429, rate limiter, connection reuse, read-only guard, and no token or signed URL in any output. All passed.

Live check (throwaway container from the rebuilt image, real token, real MCP handshake; content not logged): recent-items search 1.08 s; 3-word multi-keyword search 0.76 s and reported which keywords it also tried; results included pages and database rows; first read of a page 0.64 s, the same read again 0.00 s from the cache; a bad id returned a clean "not found or not shared" error with no token in it. The Odysseus stack itself was stopped at the time (not by Claude), so start it with `docker compose up -d` to use the new build; no `--build` needed.

Started and tested in the running container (2026-09-30): first live run passed 11 of 12. The failure was real: Odysseus's MCP layer rejected a `filter` sent as a JSON string (small models often do this), and a 400 error gave a misleading hint about API versions. Fixed both: `filter` now accepts an object or a JSON string, and a 400 now shows Notion's own explanation (for example "Could not find property with name or id: X"). After rebuilding and restarting `odysseus`, the live run passed 13 of 13: search (recent, databases, multi-keyword with a junk word), read page (cached repeat 0.002 s), read and query a real database, both filter forms, malformed filter, write-style action rejected, unknown id, and no token or signed URL in any output. Typical live latency is 0.5 to 2 s per call.

Full chat flow, verified from the container log (2026-09-29 19:10–19:12): asked in the browser UI, "Use the manage_notion tool to search my Notion for '[a page title]', read the best match, and summarise it with the link." The local model (`qwen3.6-35b-a3b`) picked `mcp__notion__manage_notion` on its own, called it three times (search, then reads; all `exit_code=0`), and answered with a correct summary and the real page link. Nothing left untested.

## Using it

Ask Odysseus, for example: "Search my Notion for [page title] and summarise it, with the link." If nothing is found, connect that page to the integration in Notion (page > ... > Connections). Sub-pages inherit the connection.

## Troubleshooting

| Symptom | Cause / fix |
| :--- | :--- |
| Model says it has no Notion access | Check the log for `Built-in MCP server registered: Built-in: Notion`. If it says "skipped (set NOTION_TOKEN...)", the token did not reach the container: check `.env` and the `docker-compose.yml` line, then restart. |
| Tool error: token invalid (401) | The token was rotated or mistyped; update `.env` and restart. |
| 403 | The integration needs the "Read content" capability. |
| 404 or empty results | The page is not shared with the integration. |
| Model ignores the tool | Say "use the manage_notion tool" in the prompt; small local models sometimes skip tools. |

## Undo

- Remove the skill: delete `Odysseus/data/skills/notion/`.
- Remove the tool: delete `Odysseus/mcp_servers/notion_server.py`, the `"notion"` entry and `_BUILTIN_REQUIRES_ENV` in `src/builtin_mcp.py`, the `NOTION_TOKEN` line in `docker-compose.yml`, then rebuild with `docker compose up -d --build odysseus`.
- Revoke access entirely: delete the integration at https://www.notion.so/profile/integrations.

## Notes

- Nothing was committed to git. The Odysseus repo already had uncommitted changes of the user's own in `builtin_mcp.py` and `docker-compose.yml`.
- No repo test was added for the new server; the checks above ran outside the repo.
- The Odysseus source changes live in the Docker image, so an Odysseus update or rebuild from a clean checkout will drop them unless they are committed.
