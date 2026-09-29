"""A tiny in-memory fake of the parts of the Notion API notion_server.py calls.

Used as an httpx.MockTransport handler so tests run with no real network
access and no real token.
"""

import json

import httpx

TOKEN = "secret_test_token_do_not_leak_ABC123"


class FakeNotion:
    def __init__(self):
        self.pages = {}
        self.databases = {}
        self.blocks = {}     # block/page id -> list of child block dicts
        self.comments = {}   # block/page id -> list of comment dicts
        self.calls = []      # every (method, path) received, in order
        self.fail_once = set()   # {(method, path)} to answer with one 429 first
        self._failed = set()

    # ---- fixture builders -------------------------------------------------

    def add_page(self, id, title, parent=None, properties=None):
        props = dict(properties or {})
        props.setdefault("Name", {"type": "title", "title": [{"plain_text": title}]})
        self.pages[id] = {
            "object": "page",
            "id": id,
            "url": f"https://notion.so/{title.replace(' ', '-')}-{id.replace('-', '')}",
            "parent": parent or {"type": "workspace", "workspace": True},
            "properties": props,
            "last_edited_time": "2026-01-01T00:00:00.000Z",
        }
        self.blocks.setdefault(id, [])
        return id

    def add_database(self, id, title, properties=None):
        self.databases[id] = {
            "object": "database",
            "id": id,
            "url": f"https://notion.so/{id.replace('-', '')}",
            "title": [{"plain_text": title}],
            "properties": properties or {"Name": {"type": "title"}, "Status": {"type": "status"}},
        }
        return id

    def add_block(self, parent_id, block_id, type_="paragraph", text="", has_children=False, extra=None):
        block = {"id": block_id, "type": type_, "has_children": has_children, type_: dict(extra or {})}
        if text:
            block[type_]["rich_text"] = [{"plain_text": text}]
        self.blocks.setdefault(parent_id, []).append(block)
        self.blocks.setdefault(block_id, [])
        return block_id

    def add_comment(self, block_id, text):
        self.comments.setdefault(block_id, []).append(
            {"rich_text": [{"plain_text": text}], "created_time": "2026-01-01T00:00:00.000Z"}
        )

    # ---- transport handler --------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/v1"):  # httpx.Client(base_url=".../v1") includes it in the request path
            path = path[len("/v1"):]
        self.calls.append((request.method, path))

        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"message": "API token is invalid."})

        key = (request.method, path)
        if key in self.fail_once and key not in self._failed:
            self._failed.add(key)
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "rate limited"})

        if request.method == "GET" and path == "/users/me":
            return httpx.Response(
                200,
                json={"object": "user", "id": "1234abcd-1234-1234-1234-1234567890ab",
                      "name": "Test Integration", "bot": {"workspace_name": "Test Workspace"}},
            )
        if request.method == "POST" and path == "/search":
            return self._search(request)
        if request.method == "GET" and path.startswith("/pages/"):
            pid = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=self.pages[pid]) if pid in self.pages else httpx.Response(404, json={"message": "not found"})
        if request.method == "GET" and path.startswith("/databases/") and not path.endswith("/query"):
            did = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=self.databases[did]) if did in self.databases else httpx.Response(404, json={"message": "not found"})
        if request.method == "POST" and path.startswith("/databases/") and path.endswith("/query"):
            return self._query(request, path.split("/")[2])
        if request.method == "GET" and path.startswith("/blocks/") and path.endswith("/children"):
            return self._children(request, path.split("/")[2])
        if request.method == "GET" and path == "/comments":
            bid = request.url.params.get("block_id")
            return httpx.Response(200, json={"results": self.comments.get(bid, []), "has_more": False, "next_cursor": None})

        # Any write-style request reaching here means notion_server.py's
        # client-side read-only guard failed to block it before the network call.
        return httpx.Response(400, json={"message": f"fake server got unexpected {request.method} {path}"})

    def _title(self, o):
        if o["object"] == "database":
            return "".join(t["plain_text"] for t in o["title"])
        for v in o["properties"].values():
            if v.get("type") == "title":
                return "".join(t["plain_text"] for t in v["title"])
        return ""

    def _search(self, request):
        body = json.loads(request.content or b"{}")
        query = (body.get("query") or "").lower()
        obj_filter = (body.get("filter") or {}).get("value")
        items = list(self.pages.values()) + list(self.databases.values())
        results = [
            o for o in items
            if (not obj_filter or o["object"] == obj_filter)
            and (not query or query in self._title(o).lower())
        ]
        if not query:
            results.sort(key=lambda o: o.get("last_edited_time", ""), reverse=True)
        return httpx.Response(200, json={"results": results, "has_more": False, "next_cursor": None})

    def _query(self, request, db_id):
        body = json.loads(request.content or b"{}")
        rows = [p for p in self.pages.values()
                if p["parent"].get("type") == "database_id" and p["parent"].get("database_id") == db_id]
        flt = body.get("filter")
        if flt:
            prop, want = flt.get("property"), (flt.get("status") or flt.get("select") or {}).get("equals")
            if prop and want is not None:
                def matches(row):
                    p = row["properties"].get(prop, {})
                    val = p.get(p.get("type")) or {}
                    return isinstance(val, dict) and val.get("name") == want
                rows = [r for r in rows if matches(r)]
        return httpx.Response(200, json={"results": rows, "has_more": False, "next_cursor": None})

    def _children(self, request, block_id):
        all_blocks = self.blocks.get(block_id, [])
        if block_id.startswith("missing-"):
            return httpx.Response(404, json={"message": "block not found"})
        cursor = request.url.params.get("start_cursor")
        page_size = int(request.url.params.get("page_size", 100))
        start = int(cursor) if cursor else 0
        page = all_blocks[start:start + page_size]
        has_more = start + page_size < len(all_blocks)
        next_cursor = str(start + page_size) if has_more else None
        return httpx.Response(200, json={"results": page, "has_more": has_more, "next_cursor": next_cursor})
