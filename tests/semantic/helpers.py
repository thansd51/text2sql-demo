"""임시 디렉터리에 메타데이터 파일을 만드는 도우미."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from text2sql.semantic import FileRepository

DATASOURCE: dict[str, Any] = {
    "id": "p001",
    "name": "시험 프로젝트",
    "db_type": "oracle",
    "db_version": "19c",
}

# 실제 DB 테이블 단위로 정의한 시험용 profile. 파일 하나가 테이블 하나다. 테이블 둘.
PRODUCT_YAML = """\
product: innoproduct
relationships:
  - from: OBJ_INV.SID
    to: OBJ_MAIN.SID
    note: 상위 오브젝트
  - from: OBJ_INV.SUBSID
    to: OBJ_MAIN.SID
    note: 하위 오브젝트
glossary:
  - 오브젝트명은 중복될 수 있다
"""

OBJ_MAIN_YAML = """\
name: OBJ_MAIN
description: 오브젝트
columns:
  - name: SID
    type: number
    description: 고유 ID (PK, 중복 없음)
  - name: BIZCODE
    type: string
    description: 오브젝트 코드
    synonyms: [상품코드, 코드]
  - name: TYPEID
    type: number
    description: 오브젝트 유형 코드
  - name: OBJ_NAME
    type: string
    description: 오브젝트명 (중복될 수 있음)
    synonyms: [상품명, 이름]
"""

OBJ_INV_YAML = """\
name: OBJ_INV
description: 오브젝트 사이의 관계
columns:
  - name: SID
    type: number
    description: 상위 오브젝트
  - name: SUBSID
    type: number
    description: 하위 오브젝트
  - name: INV_TYPE
    type: number
    description: 관계 구분
"""

# 제품 디렉터리 안의 파일 (상대 경로 -> 내용). 테이블은 파일 이름순으로 읽힌다.
PROFILE_FILES: dict[str, str] = {
    "product.yml": PRODUCT_YAML,
    "tables/OBJ_MAIN.yml": OBJ_MAIN_YAML,
    "tables/OBJ_INV.yml": OBJ_INV_YAML,
}

# 제품 공통 예시. 시험용 profile의 테이블로 쓴다.
EXAMPLES_YAML = """\
product: innoproduct
examples:
  - question: 오브젝트 이름 목록
    sql: SELECT OBJ_NAME FROM OBJ_MAIN
  - question: 유형코드가 101인 오브젝트의 코드와 이름
    sql: SELECT BIZCODE, OBJ_NAME FROM OBJ_MAIN WHERE TYPEID = 101
"""

# 프로젝트마다 다른 테이블 데이터: 테이블 -> 행 목록 (행 하나에 컬럼 여러 개, 값이 없으면 null)
SEMANTIC: dict[str, Any] = {
    "OBJ_MAIN": [
        {"TYPEID": "101", "OBJ_NAME": "장기상품"},
        {"TYPEID": "102", "OBJ_NAME": "일반상품"},
    ],
}


@dataclass(frozen=True)
class Dirs:
    datasources: Path
    semantic: Path
    profiles: Path
    examples: Path

    def repository(self) -> FileRepository:
        return FileRepository(
            self.datasources, self.semantic, self.profiles, self.examples
        )


def as_text(value: str | Mapping[str, Any]) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def make_dirs(
    root: Path,
    *,
    datasources: Mapping[str, str | Mapping[str, Any]] | None = None,
    semantics: Mapping[str, str | Mapping[str, Any]] | None = None,
    profiles: Mapping[str, Mapping[str, str]] | None = None,
    examples: Mapping[str, str] | None = None,
) -> Dirs:
    """파일명(확장자 제외) -> 내용. None이면 기본 샘플, {}이면 파일 없음.

    profiles는 제품 -> {디렉터리 안의 상대 경로: 내용}이다 (product.yml, tables/<테이블>.yml).

    examples는 기본이 '파일 없음'이다. 공통 예시가 필요한 테스트만 넘긴다.
    """
    dirs = Dirs(
        root / "datasources", root / "semantic", root / "profiles", root / "examples"
    )
    for directory in (dirs.datasources, dirs.semantic, dirs.profiles, dirs.examples):
        directory.mkdir(parents=True, exist_ok=True)
    if datasources is None:
        datasources = {"p001": DATASOURCE}
    if semantics is None:
        semantics = {"p001": SEMANTIC}
    if profiles is None:
        profiles = {"innoproduct": PROFILE_FILES}
    for name, content in datasources.items():
        (dirs.datasources / f"{name}.json").write_text(
            as_text(content), encoding="utf-8"
        )
    for name, content in semantics.items():
        (dirs.semantic / f"{name}.json").write_text(as_text(content), encoding="utf-8")
    for product, files in profiles.items():
        for relative, content in files.items():
            path = dirs.profiles / product / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    for name, content in (examples or {}).items():
        (dirs.examples / f"{name}.yml").write_text(content, encoding="utf-8")
    return dirs
