"""파일 기반 저장소.

시작할 때 모든 파일을 한 번에 읽고 검사한다. 요청 처리 중에는 파일을 읽지 않으며,
요청 값으로 경로를 만들지 않는다 (조회는 메모리의 딕셔너리에서만 한다).
오류는 모아서 MetadataError 하나로 알린다.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from text2sql.semantic.errors import MetadataError, describe_validation_error
from text2sql.semantic.models import (
    ID_PATTERN,
    DataSource,
    Example,
    ProductExamples,
    ProductFile,
    Profile,
    Semantic,
    Table,
)

_ID = re.compile(ID_PATTERN)


def _label(path: Path, depth: int = 2) -> str:
    """오류 메시지에 쓰는 파일 표시. 예: datasources/p001.json

    depth는 뒤에서 몇 단계의 경로를 보여 줄지다. 테이블 파일은 4단계
    (profiles/innoproduct/tables/OBJ_MAIN.yml)다.
    """
    return "/".join(path.parts[-depth:])


class FileRepository:
    def __init__(
        self,
        datasources_dir: Path,
        semantic_dir: Path,
        profiles_dir: Path,
        examples_dir: Path,
    ) -> None:
        self._datasources: dict[str, DataSource] = {}
        self._semantics: dict[str, Semantic] = {}
        self._profiles: dict[str, Profile] = {}
        self._examples: dict[str, ProductExamples] = {}
        # 해시용 원본. 줄바꿈과 BOM을 정규화한 텍스트를 담는다.
        self._raw_datasources: dict[str, str] = {}
        self._raw_semantics: dict[str, str] = {}
        self._raw_profiles: dict[str, str] = {}
        self._raw_examples: dict[str, str] = {}
        problems: list[str] = []

        self._load_profiles(Path(profiles_dir), problems)
        self._load_datasources(Path(datasources_dir), problems)
        self._load_semantics(Path(semantic_dir), problems)
        self._load_examples(Path(examples_dir), problems)
        self._check_references(problems)
        if problems:
            raise MetadataError(problems)

    # ---- SemanticRepository ----

    def get_datasource(self, datasource_id: str) -> DataSource | None:
        return self._datasources.get(datasource_id)

    def list_datasources(self) -> list[DataSource]:
        return [self._datasources[key] for key in sorted(self._datasources)]

    def get_semantic(self, datasource_id: str) -> Semantic:
        return self._semantics.get(datasource_id, Semantic({}))

    def get_profile(self, product: str) -> Profile | None:
        return self._profiles.get(product)

    def get_examples(self, product: str) -> tuple[Example, ...]:
        found = self._examples.get(product)
        return found.examples if found else ()

    def content_hash(self, datasource_id: str) -> str:
        datasource = self._datasources.get(datasource_id)
        if datasource is None:
            raise KeyError(datasource_id)
        digest = hashlib.sha256()
        parts = [
            ("datasource", self._raw_datasources[datasource_id]),
            *(
                (f"profile:{product}", self._raw_profiles[product])
                for product in datasource.profiles
            ),
            *(
                (f"examples:{product}", self._raw_examples.get(product, ""))
                for product in datasource.profiles
            ),
            ("semantic", self._raw_semantics.get(datasource_id, "")),
        ]
        for name, text in parts:
            digest.update(f"{name}\0{len(text)}\0{text}\0".encode())
        return digest.hexdigest()[:12]

    # ---- 읽기 ----

    def _load_datasources(self, directory: Path, problems: list[str]) -> None:
        if not directory.is_dir():
            problems.append(f"{directory.name}/: 데이터소스 디렉터리가 없습니다")
            return
        for path in _files(directory, ".json"):
            loaded = _read(path, _parse_json, problems)
            validated = _validate(DataSource, path, loaded, problems)
            if validated is None:
                continue
            model, raw = validated
            if path.stem != model.id:
                problems.append(
                    f"{_label(path)}: id: 파일명({path.stem})과 id({model.id})가 다릅니다"
                )
                continue
            self._datasources[model.id] = model
            self._raw_datasources[model.id] = raw

    def _load_semantics(self, directory: Path, problems: list[str]) -> None:
        if not directory.is_dir():
            return  # semantic은 선택이다
        for path in _files(directory, ".json"):
            if not _ID.fullmatch(path.stem):
                problems.append(
                    f"{_label(path)}: 파일명이 id 형식이 아닙니다 (허용: [a-z0-9_-]+)"
                )
                continue
            loaded = _read(path, _parse_json, problems)
            validated = _validate(Semantic, path, loaded, problems)
            if validated is None:
                continue
            self._semantics[path.stem], self._raw_semantics[path.stem] = validated

    def _load_profiles(self, directory: Path, problems: list[str]) -> None:
        """profiles/<제품>/product.yml과 profiles/<제품>/tables/<테이블>.yml을 읽는다."""
        if not directory.is_dir():
            problems.append(f"{directory.name}/: 제품 정의 디렉터리가 없습니다")
            return
        for product_dir in _directories(directory):
            self._load_product(product_dir, problems)

    def _load_product(self, product_dir: Path, problems: list[str]) -> None:
        where = f"{product_dir.parent.name}/{product_dir.name}"
        before = len(problems)

        product_path = product_dir / "product.yml"
        product_file: ProductFile | None = None
        raw_parts: list[tuple[str, str]] = []
        if not product_path.is_file():
            problems.append(f"{where}/product.yml: 파일이 없습니다")
        else:
            loaded = _read(product_path, _parse_yaml, problems, depth=3)
            validated = _validate(ProductFile, product_path, loaded, problems, depth=3)
            if validated is not None:
                product_file, text = validated
                raw_parts.append(("product.yml", text))
                if product_dir.name != product_file.product:
                    problems.append(
                        f"{where}/product.yml: product: 디렉터리명({product_dir.name})과 "
                        f"product({product_file.product})가 다릅니다"
                    )
                    product_file = None

        tables: list[Table] = []
        tables_dir = product_dir / "tables"
        table_files = _files(tables_dir, ".yml") if tables_dir.is_dir() else []
        if not table_files:
            problems.append(
                f"{where}/tables/: 테이블 파일(<테이블>.yml)이 1개 이상 필요합니다"
            )
        for path in table_files:
            loaded = _read(path, _parse_yaml, problems, depth=4)
            validated = _validate(Table, path, loaded, problems, depth=4)
            if validated is None:
                continue
            table, text = validated
            if path.stem != table.name:
                problems.append(
                    f"{_label(path, 4)}: name: 파일명({path.stem})과 "
                    f"name({table.name})이 다릅니다"
                )
                continue
            tables.append(table)
            raw_parts.append((f"tables/{path.name}", text))

        if product_file is None or len(problems) > before:
            return
        try:
            profile = Profile(
                product=product_file.product,
                tables=tuple(tables),
                relationships=product_file.relationships,
                glossary=product_file.glossary,
            )
        except ValidationError as e:
            problems.extend(describe_validation_error(f"{where}/", e))
            return
        self._profiles[profile.product] = profile
        self._raw_profiles[profile.product] = "".join(
            f"{name}\0{len(text)}\0{text}\0" for name, text in raw_parts
        )

    def _load_examples(self, directory: Path, problems: list[str]) -> None:
        if not directory.is_dir():
            return  # 공통 예시는 선택이다
        for path in _files(directory, ".yml"):
            loaded = _read(path, _parse_yaml, problems)
            validated = _validate(ProductExamples, path, loaded, problems)
            if validated is None:
                continue
            model, raw = validated
            if path.stem != model.product:
                problems.append(
                    f"{_label(path)}: product: 파일명({path.stem})과 "
                    f"product({model.product})가 다릅니다"
                )
                continue
            self._examples[model.product] = model
            self._raw_examples[model.product] = raw

    def _check_references(self, problems: list[str]) -> None:
        for datasource_id, datasource in self._datasources.items():
            for index, product in enumerate(datasource.profiles):
                if product not in self._profiles:
                    problems.append(
                        f"datasources/{datasource_id}.json: profiles[{index}]: "
                        f"제품 '{product}'에 해당하는 profiles/{product}/ 디렉터리가 없습니다"
                    )
        for product in self._examples:
            if product not in self._profiles:
                problems.append(
                    f"examples/{product}.yml: 대응하는 profiles/{product}/ 디렉터리가 없습니다"
                )
        for semantic_id in self._semantics:
            if semantic_id not in self._datasources:
                problems.append(
                    f"semantic/{semantic_id}.json: 대응하는 "
                    f"datasources/{semantic_id}.json이 없습니다"
                )


def _directories(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def _files(directory: Path, suffix: str) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix == suffix and not path.name.startswith(".")
    )


# (파싱된 값, 정규화한 원문)
_Loaded = tuple[Any, str]


def _read(
    path: Path, parse: Any, problems: list[str], depth: int = 2
) -> _Loaded | None:
    label = _label(path, depth)
    try:
        # utf-8-sig: Windows 도구가 붙인 BOM을 허용한다. 줄바꿈은 LF로 맞춰 해시를 안정시킨다.
        text = path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError:
        problems.append(f"{label}: UTF-8 인코딩으로 읽을 수 없습니다")
        return None
    except OSError:
        problems.append(f"{label}: 파일을 읽을 수 없습니다")
        return None
    try:
        return parse(text), text
    except _SyntaxProblem as e:
        problems.append(f"{label}: {e}")
        return None


class _SyntaxProblem(Exception):
    pass


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """JSON 객체의 같은 키를 거부한다. 파서가 뒤의 값만 남기고 조용히 버리는 것을 막는다."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _SyntaxProblem(f"같은 키가 두 번 적혀 있습니다: {key}")
        result[key] = value
    return result


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as e:
        raise _SyntaxProblem(
            f"{e.lineno}행 {e.colno}열: JSON 문법이 올바르지 않습니다"
        ) from e


def _parse_yaml(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"{mark.line + 1}행 {mark.column + 1}열: " if mark else ""
        raise _SyntaxProblem(f"{where}YAML 문법이 올바르지 않습니다") from e


def _validate[M: BaseModel](
    model: type[M],
    path: Path,
    loaded: _Loaded | None,
    problems: list[str],
    depth: int = 2,
) -> tuple[M, str] | None:
    """검사에 통과하면 (모델, 정규화한 원문)을 돌려준다. 원문은 해시에 쓴다."""
    if loaded is None:
        return None
    value, text = loaded
    if not isinstance(value, dict):
        problems.append(
            f"{_label(path, depth)}: (최상위): 객체(키: 값 묶음)여야 합니다"
        )
        return None
    try:
        return model.model_validate(value), text
    except ValidationError as e:
        problems.extend(describe_validation_error(_label(path, depth), e))
        return None
