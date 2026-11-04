"""
Serving the built frontend from the same FastAPI app.

Two things have to hold at once: the static file handler must set cache
headers that match Vite's hashed filenames, and the "/" mount must not
swallow the API routes once it exists.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from main import FrontendFiles, frontend_build_id

SCRIPT_TAG = '<script type="module" crossorigin src="/assets/index-abc123.js"></script>'


def _built_dist(tmp_path):
    """A miniature frontend/dist: index.html plus one hashed asset."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        f"<!doctype html><html><body>{SCRIPT_TAG}</body></html>",
        encoding="utf-8",
    )
    (tmp_path / "assets" / "index-abc123.js").write_text(
        "console.log('cardiotwin');", encoding="utf-8"
    )
    return tmp_path


def test_serves_index_with_no_cache(tmp_path):
    dist = _built_dist(tmp_path)
    app = FastAPI()
    app.mount("/", FrontendFiles(directory=str(dist), html=True), name="frontend")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert SCRIPT_TAG in response.text
    assert response.headers["Cache-Control"] == "no-cache"


def test_serves_hashed_assets_as_immutable(tmp_path):
    dist = _built_dist(tmp_path)
    app = FastAPI()
    app.mount("/", FrontendFiles(directory=str(dist), html=True), name="frontend")

    with TestClient(app) as client:
        response = client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert "immutable" in response.headers["Cache-Control"]


def test_build_id_reads_the_entry_script(tmp_path):
    dist = _built_dist(tmp_path)
    assert frontend_build_id(dist) == "index-abc123.js"


def test_build_id_is_none_for_an_empty_directory(tmp_path):
    assert frontend_build_id(tmp_path) is None


def test_build_id_is_none_for_a_missing_path(tmp_path):
    assert frontend_build_id(tmp_path / "does-not-exist") is None


def test_app_health_reports_build_key():
    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert "build" in response.json()


def test_api_routes_win_over_the_root_mount():
    with TestClient(main.app) as client:
        response = client.get("/api/laminae")

    assert response.status_code == 200
    assert "laminae" in response.json()
