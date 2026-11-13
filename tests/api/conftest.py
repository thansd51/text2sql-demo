from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeLLM
from tests.semantic.helpers import DATASOURCE, SEMANTIC, make_dirs
from text2sql.config import Settings
from text2sql.main import create_app
from text2sql.semantic import Registry, build_registry

URL = "/api/v1/text-to-sql"
GOOD = "SELECT OBJ_NAME FROM OBJ_MAIN WHERE SID = 1"


@dataclass
class Harness:
    client: TestClient
    llm: FakeLLM
    registry: Registry
    settings: Settings


HarnessFactory = Callable[..., Harness]


@pytest.fixture
def make_harness(tmp_path: Path) -> HarnessFactory:
    """가짜 LLM과 임시 메타데이터 파일로 앱을 만든다. 실제 LLM은 호출하지 않는다."""

    def factory(
        *replies: str | Exception,
        datasources: Mapping[str, Any] | None = None,
        raise_server_exceptions: bool = True,
        **settings_overrides: Any,
    ) -> Harness:
        # semantic 파일은 데이터소스마다 하나씩 둔다 (짝이 없는 semantic은 시작 오류다)
        semantics = (
            None if datasources is None else {name: SEMANTIC for name in datasources}
        )
        dirs = make_dirs(tmp_path, datasources=datasources, semantics=semantics)
        registry = build_registry(dirs.repository())
        llm = FakeLLM(*replies)
        # 화면 빌드(frontend/dist) 유무에 테스트 결과가 달라지지 않도록 없는 경로를 쓴다
        settings_overrides.setdefault(
            "frontend_dist_dir", tmp_path / "no-frontend-build"
        )
        settings = Settings(_env_file=None, **settings_overrides)
        app = create_app(settings, registry=registry, llm=llm)
        client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
        return Harness(client, llm, registry, settings)

    return factory


def two_datasources() -> dict[str, Any]:
    return {
        "p001": DATASOURCE,
        "a-pg": {
            **DATASOURCE,
            "id": "a-pg",
            "name": "PostgreSQL 프로젝트",
            "db_type": "postgresql",
            "db_version": "14",
        },
    }
