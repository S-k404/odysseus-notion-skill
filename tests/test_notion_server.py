"""Offline tests for mcp_servers/notion_server.py against a fake Notion API
(tests/fake_notion.py). No real network access and no real token are used.
"""

import json

from fake_notion import TOKEN


# ---------------------------------------------------------------------------
# env-configurable rate limit / cache TTL
# ---------------------------------------------------------------------------

def test_env_float_uses_default_when_unset(ns):
    assert ns._env_float("NOTION_DOES_NOT_EXIST", 2.8) == 2.8


def test_env_float_uses_default_for_empty_string(ns, monkeypatch):
    # docker-compose's `${VAR:-}` passthrough sets an empty string, not unset,
    # when the operator hasn't configured VAR -- must not crash on float("").
    monkeypatch.setenv("NOTION_RATE_LIMIT", "")
    assert ns._env_float("NOTION_RATE_LIMIT", 2.8) == 2.8


def test_env_float_uses_default_for_garbage(ns, monkeypatch):
    monkeypatch.setenv("NOTION_RATE_LIMIT", "not-a-number")
    assert ns._env_float("NOTION_RATE_LIMIT", 2.8) == 2.8


def test_env_float_parses_a_real_value(ns, monkeypatch):
    monkeypatch.setenv("NOTION_CACHE_TTL", "10")
    assert ns._env_float("NOTION_CACHE_TTL", 45.0) == 10.0


# ---------------------------------------------------------------------------
# id parsing
# ---------------------------------------------------------------------------

def test_extract_id_from_url(ns):
    url = "https://www.notion.so/My-Page-1234abcd1234abcd1234abcd1234abcd?pvs=4"
    assert ns._extract_id(url) == "1234abcd-1234-abcd-1234-abcd1234abcd"


def test_extract_id_from_hyphenated_uuid(ns):
    uid = "1234abcd-1234-abcd-1234-abcd1234abcd"
    assert ns._extract_id(uid) == uid


def test_extract_id_from_bare_hex(ns):
    assert ns._extract_id("1234abcd1234abcd1234abcd1234abcd") == "1234abcd-1234-abcd-1234-abcd1234abcd"


def test_extract_id_none_for_garbage(ns):
    assert ns._extract_id("not an id") is None


# ---------------------------------------------------------------------------
# read-only guard and auth
# ---------------------------------------------------------------------------

def test_write_style_request_is_blocked_before_any_network_call(ns):
    try:
        ns._request("PATCH", "/pages/1234abcd-1234-abcd-1234-abcd1234abcd", {"archived": True})
        assert False, "expected NotionError"
    except ns.NotionError as e:
        assert "read-only" in str(e).lower()
    assert ns.fake.calls == []  # never reached the fake network


def test_post_to_non_search_non_query_path_is_blocked(ns):
    try:
        ns._request("POST", "/pages", {"parent": {}, "properties": {}})
        assert False, "expected NotionError"
    except ns.NotionError:
        pass
    assert ns.fake.calls == []


def test_missing_token_is_reported_without_a_network_call(ns, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    try:
        ns._request("GET", "/users/me")
        assert False, "expected NotionError"
    except ns.NotionError as e:
        assert "NOTION_TOKEN" in str(e)
    assert ns.fake.calls == []


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def test_search_ranks_full_phrase_match_first(ns):
    ns.fake.add_page("11111111-1111-1111-1111-111111111111", "ECE Hub")
    ns.fake.add_page("22222222-2222-2222-2222-222222222222", "ECE Homework")
    out = ns._do_search(query="ece hub")
    lines = out.splitlines()
    assert "ECE Hub" in lines[1]
    assert "ECE Homework" not in lines[1]


def test_search_also_tries_each_keyword(ns):
    ns.fake.add_page("11111111-1111-1111-1111-111111111111", "Odysseus Notes")
    out = ns._do_search(query="odysseus junkword")
    assert "Odysseus Notes" in out
    assert "also tried" in out


def test_search_kind_filters_to_database(ns):
    ns.fake.add_page("11111111-1111-1111-1111-111111111111", "Tasks")
    ns.fake.add_database("22222222-2222-2222-2222-222222222222", "Tasks")
    out = ns._do_search(query="tasks", kind="database")
    assert "[database]" in out
    assert "[page]" not in out


def test_empty_query_returns_most_recently_edited(ns):
    ns.fake.add_page("11111111-1111-1111-1111-111111111111", "Old")
    ns.fake.pages["11111111-1111-1111-1111-111111111111"]["last_edited_time"] = "2020-01-01T00:00:00.000Z"
    ns.fake.add_page("22222222-2222-2222-2222-222222222222", "New")
    ns.fake.pages["22222222-2222-2222-2222-222222222222"]["last_edited_time"] = "2026-01-01T00:00:00.000Z"
    out = ns._do_search(query="")
    assert out.splitlines()[1].startswith("- New")


def test_search_no_match_explains_titles_only(ns):
    out = ns._do_search(query="nothing matches this")
    assert "TITLES" in out


# ---------------------------------------------------------------------------
# read: pages, properties, nested blocks, find, comments
# ---------------------------------------------------------------------------

def test_read_page_includes_properties_blocks_and_comments(ns):
    pid = "11111111-1111-1111-1111-111111111111"
    ns.fake.add_page(pid, "Project Plan", properties={
        "Status": {"type": "status", "status": {"name": "In Progress"}},
    })
    ns.fake.add_block(pid, "b1", "heading_1", "Overview")
    ns.fake.add_block(pid, "b2", "paragraph", "This is the plan.")
    ns.fake.add_comment(pid, "Looks good to me")

    out = ns._do_read(pid)

    assert "# Project Plan" in out
    assert "Status: In Progress" in out
    assert "# Overview" in out
    assert "This is the plan." in out
    assert "Comments:" in out
    assert "Looks good to me" in out
    assert "not instructions" in out  # untrusted-data label from _UNTRUSTED


def test_read_renders_nested_children_indented(ns):
    pid = "11111111-1111-1111-1111-111111111111"
    ns.fake.add_page(pid, "Nested")
    ns.fake.add_block(pid, "parent-item", "bulleted_list_item", "Parent item", has_children=True)
    ns.fake.add_block("parent-item", "child-item", "bulleted_list_item", "Child item")
    out = ns._do_read(pid)
    assert "- Parent item" in out
    assert "  - Child item" in out


def test_read_find_returns_only_matching_lines_with_context(ns):
    pid = "11111111-1111-1111-1111-111111111111"
    ns.fake.add_page(pid, "Long Page")
    for i in range(10):
        ns.fake.add_block(pid, f"b{i}", "paragraph", f"line {i}")
    ns.fake.add_block(pid, "special", "paragraph", "the needle sentence")
    out = ns._do_read(pid, find="needle")
    assert "the needle sentence" in out
    assert "showing only lines matching 'needle'" in out
    assert "line 0" not in out  # far outside the small context window


def test_read_skips_a_sub_block_notion_refuses_instead_of_failing(ns):
    pid = "11111111-1111-1111-1111-111111111111"
    ns.fake.add_page(pid, "Has A Broken Child")
    ns.fake.add_block(pid, "missing-child", "paragraph", "parent text", has_children=True)
    ns.fake.blocks["missing-child"] = []  # unused; handler 404s on "missing-" ids regardless
    out = ns._do_read(pid)
    assert "parent text" in out  # read succeeds despite the child 404ing


def test_read_database_returns_schema_and_rows(ns):
    did = "33333333-3333-3333-3333-333333333333"
    ns.fake.add_database(did, "Tasks", properties={"Name": {"type": "title"}, "Status": {"type": "status"}})
    ns.fake.add_page("11111111-1111-1111-1111-111111111111", "Task A", parent={"type": "database_id", "database_id": did})
    out = ns._do_read(did)
    assert "This is a database" in out
    assert "Columns: Name (title), Status (status)" in out
    assert "Task A" in out


def test_read_unknown_id_gives_clean_not_found_error(ns):
    # _do_read itself raises NotionError; call_tool() is what turns that into
    # "Error: ...", so replicate that translation here.
    try:
        ns._do_read("99999999-9999-9999-9999-999999999999")
        assert False, "expected NotionError"
    except ns.NotionError as e:
        assert "not found" in str(e) or "not shared" in str(e)


def test_read_max_chars_clips_output(ns):
    pid = "11111111-1111-1111-1111-111111111111"
    ns.fake.add_page(pid, "Big Page")
    ns.fake.add_block(pid, "b1", "paragraph", "x" * 5000)
    out = ns._do_read(pid, max_chars=200)
    assert len(out) < 400
    assert "truncated" in out


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

def test_query_filters_rows_with_dict_filter(ns):
    did = "33333333-3333-3333-3333-333333333333"
    ns.fake.add_database(did, "Tasks")
    ns.fake.add_page("11111111-1111-1111-1111-111111111111", "Done Task",
                      parent={"type": "database_id", "database_id": did},
                      properties={"Status": {"type": "status", "status": {"name": "Done"}}})
    ns.fake.add_page("22222222-2222-2222-2222-222222222222", "Open Task",
                      parent={"type": "database_id", "database_id": did},
                      properties={"Status": {"type": "status", "status": {"name": "Open"}}})
    out = ns._do_query(did, {"property": "Status", "status": {"equals": "Done"}}, 25)
    assert "Done Task" in out
    assert "Open Task" not in out


def test_query_accepts_filter_as_json_string(ns):
    did = "33333333-3333-3333-3333-333333333333"
    ns.fake.add_database(did, "Tasks")
    ns.fake.add_page("11111111-1111-1111-1111-111111111111", "Done Task",
                      parent={"type": "database_id", "database_id": did},
                      properties={"Status": {"type": "status", "status": {"name": "Done"}}})
    flt = json.dumps({"property": "Status", "status": {"equals": "Done"}})
    out = ns._do_query(did, flt, 25)
    assert "Done Task" in out


def test_query_rejects_malformed_filter_string(ns):
    did = "33333333-3333-3333-3333-333333333333"
    ns.fake.add_database(did, "Tasks")
    out = ns._do_query(did, "{not json", 25)
    assert "Error" in out
    assert ns.fake.calls == []  # rejected before any request


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------

def test_ping_reports_workspace(ns):
    out = ns._do_ping()
    assert "Test Workspace" in out
    assert "Test Integration" in out


# ---------------------------------------------------------------------------
# dispatch / schema-level behavior
# ---------------------------------------------------------------------------

def test_dispatch_rejects_unknown_action(ns):
    out = ns._dispatch({"action": "delete", "id": "x"})
    assert "Unknown action" in out


def test_dispatch_routes_every_known_action(ns):
    pid = ns.fake.add_page("11111111-1111-1111-1111-111111111111", "Routing Test")
    assert "Routing Test" not in ns._dispatch({"action": "search", "query": "nope"})
    assert "Routing Test" in ns._dispatch({"action": "search", "query": "Routing"})
    assert "Routing Test" in ns._dispatch({"action": "read", "id": pid})
    assert "Test Workspace" in ns._dispatch({"action": "ping"})


# ---------------------------------------------------------------------------
# caching and fresh=true
# ---------------------------------------------------------------------------

def test_identical_read_is_served_from_cache(ns):
    pid = "11111111-1111-1111-1111-111111111111"
    ns.fake.add_page(pid, "Cached Page")
    ns._do_read(pid)
    calls_after_first = len(ns.fake.calls)
    ns._do_read(pid)
    assert len(ns.fake.calls) == calls_after_first  # second read hit the cache, no new requests


def test_fresh_true_bypasses_the_cache(ns):
    pid = "11111111-1111-1111-1111-111111111111"
    ns.fake.add_page(pid, "Cached Page")
    ns._dispatch({"action": "read", "id": pid})
    calls_after_first = len(ns.fake.calls)
    ns._dispatch({"action": "read", "id": pid, "fresh": True})
    assert len(ns.fake.calls) > calls_after_first


# ---------------------------------------------------------------------------
# retry / rate limiting
# ---------------------------------------------------------------------------

def test_429_is_retried_and_eventually_succeeds(ns):
    ns.fake.fail_once.add(("GET", "/users/me"))
    out = ns._do_ping()
    assert "Test Workspace" in out
    assert ("GET", "/users/me") in ns.fake.calls
    # the endpoint was hit at least twice: the 429 and the retry that followed
    assert sum(1 for c in ns.fake.calls if c == ("GET", "/users/me")) >= 2


def test_rate_limiter_paces_requests(ns):
    import time
    ns._limiter._interval = 0.05  # speed up the test without changing the logic under test
    ns._limiter._burst = 1        # so the second call can't ride the first's burst credit
    start = time.monotonic()
    ns._request("GET", "/users/me")
    ns._request("GET", "/users/me", params={"cache_buster": "1"})  # different key: skips the cache
    elapsed = time.monotonic() - start
    assert elapsed >= 0.04  # second call had to wait roughly one interval


# ---------------------------------------------------------------------------
# nothing sensitive ever leaks into tool output
# ---------------------------------------------------------------------------

def test_token_never_appears_in_any_output(ns):
    pid = "11111111-1111-1111-1111-111111111111"
    did = "33333333-3333-3333-3333-333333333333"
    ns.fake.add_page(pid, "Some Page")
    ns.fake.add_database(did, "Some DB")
    ns.fake.add_comment(pid, "a comment")

    outputs = [
        ns._do_search(query="some"),
        ns._do_read(pid),
        ns._do_read(did),
        ns._do_ping(),
        ns._dispatch({"action": "bogus"}),
    ]
    try:
        ns._request("DELETE", "/pages/" + pid)
    except ns.NotionError as e:
        outputs.append(str(e))
    try:
        ns._do_read("not-an-id")
    except Exception:
        pass

    for out in outputs:
        assert TOKEN not in out
        assert "Bearer" not in out
