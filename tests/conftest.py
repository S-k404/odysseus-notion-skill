import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from fake_notion import TOKEN, FakeNotion

_MODULE_PATH = Path(__file__).resolve().parent.parent / "mcp_servers" / "notion_server.py"


def _load_fresh_module():
    """Load notion_server.py as a brand-new module object so every test gets
    its own cache, rate limiter and http client instead of sharing state."""
    spec = importlib.util.spec_from_file_location("notion_server_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ns(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", TOKEN)
    module = _load_fresh_module()
    fake = FakeNotion()
    module._http = httpx.Client(
        base_url=module._API_BASE,
        headers={"Authorization": f"Bearer {TOKEN}", "Notion-Version": module._NOTION_VERSION},
        transport=httpx.MockTransport(fake.handler),
    )
    module.fake = fake
    yield module
    module._http.close()
    module._IO_POOL.shutdown(wait=False)
    module._TASK_POOL.shutdown(wait=False)
