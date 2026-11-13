from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.semantic.helpers import (
    DATASOURCE,
    EXAMPLES_YAML,
    SEMANTIC,
    make_dirs,
)
from text2sql.semantic import ProjectMetadata, build_registry

MetadataFactory = Callable[..., ProjectMetadata]

# 시험용 profile(tests/semantic/helpers.py)의 테이블: OBJ_MAIN(SID, BIZCODE, TYPEID, OBJ_NAME),
# OBJ_INV(SID, SUBSID, INV_TYPE)
GOOD = "SELECT OBJ_NAME FROM OBJ_MAIN WHERE SID = 1"
BAD_COLUMN = "SELECT NO_SUCH FROM OBJ_MAIN"
BAD_TABLE = "SELECT * FROM OBJ_DETAIL"
MAX_ROWS = 100


@pytest.fixture
def make_metadata(tmp_path: Path) -> MetadataFactory:
    """시험용 ProjectMetadata를 만든다. 공통 예시가 들어 있다."""

    def factory(
        db_type: str = "oracle",
        db_version: str = "19c",
        semantic: dict[str, Any] | None = None,
        profile: dict[str, str] | None = None,
        examples: str | None = EXAMPLES_YAML,
    ) -> ProjectMetadata:
        dirs = make_dirs(
            tmp_path,
            profiles=None if profile is None else {"innoproduct": profile},
            examples=None if examples is None else {"innoproduct": examples},
            datasources={
                "p001": {**DATASOURCE, "db_type": db_type, "db_version": db_version}
            },
            semantics={"p001": SEMANTIC if semantic is None else semantic},
        )
        metadata = build_registry(dirs.repository()).get("p001")
        assert metadata is not None
        return metadata

    return factory


@pytest.fixture
def metadata(make_metadata: MetadataFactory) -> ProjectMetadata:
    return make_metadata()
