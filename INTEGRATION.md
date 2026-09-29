# Wiring this into Odysseus

This repo is self-contained: the skill (`notion/notion-search/SKILL.md`) and the
tool implementation (`mcp_servers/notion_server.py`). To use it, an Odysseus
checkout needs three small edits. None of this is committed to the Odysseus
repo itself — apply it there by hand (or script it) after cloning this repo
alongside it.

## 0. (Optional) run the tests first

```bash
pip install -r tests/requirements.txt
pytest tests/
```

These run against a fake Notion API (no real token needed) and check the
read-only guard, search ranking, reads, queries, caching, retries, and that
the token never leaks into output. Useful to confirm the copy you're about
to install actually behaves as documented.

## 1. Copy the tool

```bash
cp mcp_servers/notion_server.py /path/to/Odysseus/mcp_servers/notion_server.py
```

## 2. Register it — `src/builtin_mcp.py`

Add an entry to `_BUILTIN_SERVERS`:

```python
"notion":     ("mcp_servers/notion_server.py",     "Built-in: Notion (read-only)"),
```

Add a new table (or extend an existing one) so the server is skipped, not
crashed, when no token is configured:

```python
# Built-in servers that need a credential and are skipped when it is unset:
# server id -> environment variable that must be non-empty.
_BUILTIN_REQUIRES_ENV = {"notion": "NOTION_TOKEN"}
```

And in `register_builtin_servers`, before a built-in server is started, skip
it if its required env var is unset:

```python
for server_id, (script, name) in _BUILTIN_SERVERS.items():
    required_env = _BUILTIN_REQUIRES_ENV.get(server_id)
    if required_env and not os.environ.get(required_env, "").strip():
        logger.info(f"Built-in MCP server skipped (set {required_env} to enable): {name}")
        continue
    ...
```

## 3. Pass the token through — `docker-compose.yml`

Add one line to the `odysseus` service's `environment:` block:

```yaml
- NOTION_TOKEN=${NOTION_TOKEN:-}
```

## 4. Set the token — `.env`

Copy `.env.example` from this repo into your Odysseus checkout as `.env` (or
append its `NOTION_TOKEN=` line to the `.env` you already have there), then
fill in your token:

```bash
cp .env.example /path/to/Odysseus/.env   # or append the NOTION_TOKEN line by hand
```

`.env.example` walks through creating the Notion integration and sharing
pages with it. `.env` holds a real secret — never commit it.

## 5. (Optional) tune rate limit and cache

Two environment variables override the tool's defaults, if needed:

```yaml
- NOTION_RATE_LIMIT=${NOTION_RATE_LIMIT:-}   # requests/s average; default 2.8
- NOTION_CACHE_TTL=${NOTION_CACHE_TTL:-}     # seconds; default 45, 0 disables reads from cache
```

## 6. Rebuild

```bash
docker compose up -d --build odysseus
```

Check the startup log for:

```
MCP server connected: Built-in: Notion (read-only) (notion) - 1 tools via stdio
```

See `LOG.md` for the full build history, verification steps, and
troubleshooting table.
