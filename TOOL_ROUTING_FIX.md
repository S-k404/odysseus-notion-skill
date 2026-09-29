# Fix: agent never reaches manage_notion for short prompts

Optional patch to Odysseus core (`src/agent_loop.py`), outside this repo's own
tool/skill files. Apply it only if you hit the symptom below — it may already
be fixed in a newer Odysseus release.

## Symptom

A short prompt naming Notion, with a workspace active — e.g. "check notion
project HQ" or "find project hq in notion" — never calls `manage_notion`.
Instead the model loops calling `web_search` several times trying to look up
`mcp__notion__manage_notion` by name (it knows the tool exists from earlier
context but was never actually given it this turn), until you stop it.
Longer, explicit prompts ("Use the manage_notion tool to search my Notion for
X") are unaffected — this only hits short/vague phrasing.

## Root cause

Odysseus's intent classifier (`_classify_agent_request`) flags a turn
`low_signal` when no keyword matches a known domain. With an active
workspace, a low-signal turn short-circuits to file-exploration tools only
and skips real tool retrieval — "notion" isn't a recognized domain keyword,
so a query that's just "notion" plus filler words never reaches the tool.

Odysseus already has a fix for this exact class of bug for other named
integrations (issue `#3794`, the `api_call`/Home Assistant case): detect the
service name with a keyword regex and seed the real tool deterministically,
independent of embedding retrieval. Notion and Obsidian (the other built-in
read-only knowledge-source MCP tool, same risk) never got the same treatment.

## The four edits

All in `src/agent_loop.py`. Each is additive — find the existing block below
and add the new lines next to it; nothing existing is removed.

**1. `_DOMAIN_TOOL_MAP`** (a dict literal near the top of the file) — add two
entries so these domains resolve to the actual built-in tool names, matching
the `mcp__<server id>__<tool name>` registration pattern:

```python
    "contacts": {"resolve_contact", "manage_contact"},
    "integrations": {"api_call"},
    # Built-in read-only knowledge-source MCP tools, registered as
    # mcp__<server id>__<tool name>. Harmless to seed even when the server
    # isn't registered (e.g. NOTION_TOKEN unset) -- unknown tool names are
    # dropped later when the schema list is filtered to actually-available
    # tools.
    "notion": {"mcp__notion__manage_notion"},
    "obsidian": {"mcp__obsidian__manage_obsidian"},
}
```

**2. `_classify_agent_request`** — add keyword detection right before
`low_signal = not continuation and not domains` (after the existing
`"integrations"` regex block):

```python
    # Named built-in read-only knowledge sources (Notion, Obsidian): naming
    # one alone ("check notion project HQ") matches no other domain, so with
    # an active workspace the low-signal short-circuit below served only
    # file tools and skipped RAG retrieval entirely -- the model then had no
    # way to reach the real tool and looped calling web_search to try to look
    # it up by name instead. Same fix shape as the #3794 api_call case above:
    # seed the actual built-in tool deterministically, independent of
    # embedding retrieval.
    if has(r"\bnotion\b"):
        domains.add("notion")
    if has(r"\bobsidian\b"):
        domains.add("obsidian")
```

**3. `_TERMINUS_PRESERVED_DOMAINS`** — a separate "Terminus" workspace
override (unrelated to the low-signal path above) replaces the whole tool set
for phrasing that also looks like a coding request (e.g. "read notion project
HQ" — "read" is an action verb, "project" is a target keyword in that
heuristic). It preserves tools from a fixed list of domains; add these two so
it doesn't strip the seeded tool back out:

```python
_TERMINUS_PRESERVED_DOMAINS = ("documents", "email", "notes_calendar_tasks", "ui", "sessions", "notion", "obsidian")
```

**4. `_DOMAIN_RULES`** — a *second*, separate dict keyed by the same domain
names, supplying system-prompt guidance text. `_domain_rules_for_tools()`
does a plain `_DOMAIN_RULES[domain]` lookup (no `.get`/default) for every
domain in `_DOMAIN_TOOL_MAP` whose tools ended up selected — so step 1 alone
causes a `KeyError: 'notion'` crash on every real Notion request the moment
the tool actually gets selected. This step is not optional if you did step 1.
Add matching entries, in the same style as the existing ones (e.g.
`"integrations"`):

```python
    "integrations": """\
## Integration/API rules
- To query or control a configured service integration (Home Assistant, Miniflux, Gitea, Linkding, Jellyfin, or any other registered service), use `api_call` with the integration name, HTTP method, path, and optional JSON body.
- Do not use shell, curl, or `app_api` to reach a user's connected integration when `api_call` is available.""",
    "notion": """\
## Notion rules
- Use `manage_notion` (mcp__notion__manage_notion) for every Notion request: search, read, query, ping. It is live and read-only; nothing is written to Notion or saved to disk.
- Search matches page/database TITLES only, not body text. Read the best hits and follow id= values for sub-pages and inline databases.
- Only pages shared with the integration are visible; a 404 or empty result usually means "not shared", not "does not exist".
- Do not use web_search, web_fetch, the browser, or shell to reach Notion when `manage_notion` is available.""",
    "obsidian": """\
## Obsidian rules
- Use the built-in Obsidian tool for vault search/read/write requests instead of shelling out to the filesystem.
- Confirm the configured vault path with the tool itself if a note can't be found rather than guessing paths.""",
}
```

## Verifying the fix took

```python
# from an Odysseus shell / docker exec:
from src.agent_loop import _classify_agent_request, _DOMAIN_RULES, _DOMAIN_TOOL_MAP
r = _classify_agent_request([], "find project hq in notion")
assert r["low_signal"] is False and "notion" in r["domains"]
assert "notion" in _DOMAIN_RULES  # would KeyError downstream otherwise
```

Then rebuild/restart (`docker compose up -d --build odysseus`) and check the
startup log for no traceback, and `docker logs` for no
`KeyError: 'notion'` the next time you actually ask about Notion.

## Applies to Obsidian too

Same bug class, same fix — Odysseus's built-in Obsidian tool had the
identical latent risk (never previously triggered a `KeyError` since it
wasn't in `_DOMAIN_TOOL_MAP` either, but was just as likely to lose the
low-signal race). No separate Obsidian-specific server changes needed; this
patch covers both.
