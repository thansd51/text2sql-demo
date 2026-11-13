"""레지스트리는 import가 아니라 앱 시작 때 만든다 (docs/design.md)."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.semantic.helpers import DATASOURCE, EXAMPLES_YAML, make_dirs
from text2sql.config import Settings
from text2sql.main import create_app
from text2sql.semantic import MetadataError

HANGUL = re.compile(r"[가-힣]")
REPO_ROOT = Path(__file__).resolve().parents[2]


def settings_for(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        datasources_dir=tmp_path / "datasources",
        semantic_dir=tmp_path / "semantic",
        profiles_dir=tmp_path / "profiles",
        examples_dir=tmp_path / "examples",
        frontend_dist_dir=tmp_path / "no-frontend-build",
        **overrides,  # type: ignore[arg-type]
    )


def test_startup_loads_the_registry_from_files(tmp_path: Path) -> None:
    make_dirs(tmp_path)

    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/api/v1/datasources")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["p001"]


def test_startup_works_with_the_sample_files_in_the_repository() -> None:
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/api/v1/datasources")

    items = response.json()
    assert [item["id"] for item in items] == [f"p00{n}" for n in range(1, 7)]
    assert {(i["db_type"], i["db_version"]) for i in items} == {
        ("oracle", "19c"),
        ("oracle", "11g"),
        ("oracle", "12c"),
        ("postgresql", "14"),
        ("postgresql", "16"),
    }
    assert items[0] == {
        "id": "p001",
        "name": "샘플 프로젝트 1",
        "db_type": "oracle",
        "db_version": "19c",
    }


def test_creating_the_app_reads_no_files(tmp_path: Path) -> None:
    # 디렉터리가 없어도 앱 객체는 만들어진다. 파일은 시작(lifespan)에서만 읽는다.
    app = create_app(settings_for(tmp_path / "missing"))

    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_startup_fails_on_invalid_metadata_with_file_and_location(
    tmp_path: Path,
) -> None:
    make_dirs(tmp_path, datasources={"p001": {**DATASOURCE, "db_type": "mysql"}})

    with (
        pytest.raises(MetadataError) as info,
        TestClient(create_app(settings_for(tmp_path))),
    ):
        pass

    message = info.value.message
    assert "datasources/p001.json: db_type:" in message
    assert HANGUL.search(message)


def test_startup_fails_on_missing_datasource_directory(tmp_path: Path) -> None:
    with (
        pytest.raises(MetadataError) as info,
        TestClient(create_app(settings_for(tmp_path))),
    ):
        pass

    assert "datasources/" in info.value.message


@pytest.mark.parametrize("db_version", ["abc", "v12", "c19"])
def test_startup_fails_when_a_db_version_cannot_be_read(
    tmp_path: Path, db_version: str
) -> None:
    make_dirs(tmp_path, datasources={"p001": {**DATASOURCE, "db_version": db_version}})

    with (
        pytest.raises(MetadataError) as info,
        TestClient(create_app(settings_for(tmp_path))),
    ):
        pass

    assert "datasources/p001.json" in info.value.message
    assert "DB 버전을 해석할 수 없습니다" in info.value.message


def test_requests_before_startup_finishes_are_500_not_a_crash(tmp_path: Path) -> None:
    # 컨텍스트 매니저 없이 쓰면 lifespan이 돌지 않아 레지스트리가 없다
    app = create_app(settings_for(tmp_path))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/datasources")

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "서버 내부 오류입니다",
    }


def test_injected_registry_and_llm_are_used_without_startup_loading(
    tmp_path: Path,
) -> None:
    # 주입하면 파일이 없어도 시작에 실패하지 않는다 (테스트용 경로)
    from tests.fakes import FakeLLM
    from text2sql.semantic import build_registry

    dirs = make_dirs(tmp_path / "real")
    registry = build_registry(dirs.repository())
    app = create_app(
        settings_for(tmp_path / "missing"), registry=registry, llm=FakeLLM()
    )

    with TestClient(app) as client:
        assert client.get("/api/v1/datasources").status_code == 200


# ---- 공통 예시는 시작할 때 모든 프로젝트의 DB에서 검사한다 ----


def test_startup_passes_with_valid_common_examples(tmp_path: Path) -> None:
    make_dirs(tmp_path, examples={"innoproduct": EXAMPLES_YAML})

    with TestClient(create_app(settings_for(tmp_path))) as client:
        assert client.get("/api/v1/datasources").status_code == 200


def test_startup_fails_when_a_common_example_uses_an_unknown_column(
    tmp_path: Path,
) -> None:
    broken = (
        EXAMPLES_YAML
        + "  - question: 없는 컬럼\n    sql: SELECT NO_SUCH FROM OBJ_MAIN\n"
    )
    make_dirs(tmp_path, examples={"innoproduct": broken})

    with (
        pytest.raises(MetadataError) as info,
        TestClient(create_app(settings_for(tmp_path))),
    ):
        pass

    message = info.value.message
    assert "p001(oracle 19c)" in message
    assert "공통 예시 '없는 컬럼'가 통과하지 못했습니다" in message
    assert "COLUMN_NOT_ALLOWED" in message
    assert HANGUL.search(message)


def test_startup_checks_the_examples_against_each_projects_own_database(
    tmp_path: Path,
) -> None:
    # `= ''` 비교는 PostgreSQL에서는 괜찮지만 Oracle에서는 거부된다. 프로젝트마다 따로 본다.
    only_oracle_breaks = (
        EXAMPLES_YAML
        + "  - question: 빈 문자열\n    sql: SELECT SID FROM OBJ_MAIN WHERE OBJ_NAME = ''\n"
    )
    make_dirs(
        tmp_path,
        datasources={
            "p001": DATASOURCE,
            "p002": {
                **DATASOURCE,
                "id": "p002",
                "db_type": "postgresql",
                "db_version": "14",
            },
        },
        semantics={},
        examples={"innoproduct": only_oracle_breaks},
    )

    with (
        pytest.raises(MetadataError) as info,
        TestClient(create_app(settings_for(tmp_path))),
    ):
        pass

    message = info.value.message
    assert "p001(oracle 19c)" in message and "DIALECT_RULE" in message
    assert "p002" not in message  # PostgreSQL에서는 통과한다
    assert len(info.value.problems) == 1


def test_startup_reports_a_bad_example_once_per_project(tmp_path: Path) -> None:
    broken = (
        EXAMPLES_YAML
        + "  - question: 틀린 예시\n    sql: SELECT NO_SUCH FROM OBJ_MAIN\n"
    )
    make_dirs(
        tmp_path,
        datasources={"p001": DATASOURCE, "p002": {**DATASOURCE, "id": "p002"}},
        semantics={},
        examples={"innoproduct": broken},
    )

    with (
        pytest.raises(MetadataError) as info,
        TestClient(create_app(settings_for(tmp_path))),
    ):
        pass

    assert len(info.value.problems) == 2
    assert {p.split("(")[0] for p in info.value.problems} == {"p001", "p002"}
