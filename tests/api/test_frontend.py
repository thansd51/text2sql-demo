"""frontend/dist가 있으면 FastAPI가 화면을 같은 출처로 제공한다 (CLAUDE.md)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import GOOD, URL
from tests.fakes import FakeLLM
from tests.semantic.helpers import make_dirs
from text2sql.config import Settings
from text2sql.main import create_app
from text2sql.semantic import build_registry

INDEX = "<!doctype html><title>화면</title><div id='root'></div>"


def make_dist(root: Path) -> Path:
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('x')", encoding="utf-8")
    return dist


def client_for(tmp_path: Path, dist: Path, *replies: str) -> TestClient:
    registry = build_registry(make_dirs(tmp_path / "meta").repository())
    settings = Settings(_env_file=None, frontend_dist_dir=dist)
    app = create_app(settings, registry=registry, llm=FakeLLM(*replies))
    return TestClient(app)


def test_the_built_frontend_is_served_at_the_root(tmp_path: Path) -> None:
    client = client_for(tmp_path, make_dist(tmp_path))

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<div id='root'>" in response.text


def test_assets_are_served(tmp_path: Path) -> None:
    client = client_for(tmp_path, make_dist(tmp_path))

    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert "console.log" in response.text


def test_api_routes_still_win_over_the_static_files(tmp_path: Path) -> None:
    client = client_for(tmp_path, make_dist(tmp_path), GOOD)

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/datasources").json()[0]["id"] == "p001"
    response = client.post(URL, json={"question": "상품", "datasource_id": "p001"})
    assert response.status_code == 200
    assert response.json()["status"] == "OK"


def test_api_errors_keep_the_json_error_shape_with_the_frontend_mounted(
    tmp_path: Path,
) -> None:
    client = client_for(tmp_path, make_dist(tmp_path))

    response = client.post(URL, json={"question": "상품", "datasource_id": "nope"})

    assert response.status_code == 400
    assert response.json()["code"] == "DATASOURCE_NOT_FOUND"


def test_files_outside_the_dist_folder_are_not_reachable(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("비밀", encoding="utf-8")
    client = client_for(tmp_path, make_dist(tmp_path))

    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        response = client.get(path)
        assert "비밀" not in response.text, path


def test_unknown_paths_are_404(tmp_path: Path) -> None:
    client = client_for(tmp_path, make_dist(tmp_path))

    assert client.get("/nothing-here.js").status_code == 404


@pytest.mark.parametrize("make", ["missing", "empty"])
def test_no_frontend_is_mounted_without_a_build(tmp_path: Path, make: str) -> None:
    dist = tmp_path / "dist"
    if make == "empty":
        dist.mkdir()
    client = client_for(tmp_path, dist)

    assert client.get("/").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}  # API는 그대로 동작한다
