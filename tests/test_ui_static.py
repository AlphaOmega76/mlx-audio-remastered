"""Caching rules for the built web UI served by the API server (mlx_audio/ui_static.py)."""

import glob

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mlx_audio import ui_static


def _client():
    if not ui_static.ui_is_built():
        pytest.skip("the UI is not built (cd mlx_audio/ui && npm run build)")
    app = FastAPI()
    assert ui_static.mount_ui(app)
    return TestClient(app)


def test_pages_are_always_revalidated():
    # Without this, a window or tab keeps an old copy of a page after the UI is rebuilt.
    r = _client().get("/text-to-speech/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_unchanged_pages_answer_not_modified():
    c = _client()
    first = c.get("/text-to-speech/")
    again = c.get("/text-to-speech/", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"


def test_hashed_scripts_are_cached_for_good():
    c = _client()
    script = glob.glob(str(ui_static.UI_DIST / "_next" / "static" / "chunks" / "*.js"))[0]
    r = c.get("/" + str(script).split("/out/")[1])
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"] and "max-age=31536000" in r.headers["cache-control"]
