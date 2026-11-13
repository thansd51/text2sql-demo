"""시작 시 만드는 레지스트리 (docs/design.md "시작 시 동작").

저장소에서 읽은 데이터소스, profile, 공통 예시, semantic을 병합하고 코드표가 실제
테이블.컬럼과 맞는지 확인해 둔다. 요청 처리는 이 레지스트리에서만 조회한다.
datasource_id로 파일 경로를 만들지 않는다.
"""

from text2sql.semantic.errors import MetadataError
from text2sql.semantic.models import (
    DataSource,
    Example,
    ProjectMetadata,
    Relationship,
    Semantic,
    Table,
)
from text2sql.semantic.repository import SemanticRepository


class Registry:
    def __init__(self, entries: dict[str, ProjectMetadata]) -> None:
        self._entries = dict(entries)

    def get(self, datasource_id: str) -> ProjectMetadata | None:
        """등록된 데이터소스의 메타데이터. 없으면 None (호출자가 400으로 응답한다)."""
        return self._entries.get(datasource_id)

    def all_entries(self) -> list[ProjectMetadata]:
        return [self._entries[key] for key in sorted(self._entries)]

    def datasources(self) -> list[DataSource]:
        return [entry.datasource for entry in self.all_entries()]


def build_registry(repository: SemanticRepository) -> Registry:
    """저장소 내용으로 레지스트리를 만든다. 문제가 있으면 모아서 MetadataError로 알린다."""
    problems: list[str] = []
    entries: dict[str, ProjectMetadata] = {}
    for datasource in repository.list_datasources():
        entry = _build_entry(repository, datasource, problems)
        if entry is not None:
            entries[datasource.id] = entry
    if problems:
        # 같은 profile을 쓰는 데이터소스가 여럿이면 같은 문제가 반복되므로 중복을 없앤다
        raise MetadataError(list(dict.fromkeys(problems)))
    return Registry(entries)


def _build_entry(
    repository: SemanticRepository, datasource: DataSource, problems: list[str]
) -> ProjectMetadata | None:
    before = len(problems)
    where = f"datasources/{datasource.id}.json"
    tables: list[Table] = []
    owner: dict[str, str] = {}  # 테이블 이름(대문자) -> 정의한 제품
    glossary: list[str] = []
    # (출처 표시, 관계). 출처는 오류 메시지에 쓴다
    relationships: list[tuple[str, Relationship]] = []
    examples: list[Example] = []

    for index, product in enumerate(datasource.profiles):
        profile = repository.get_profile(product)
        if profile is None:
            problems.append(
                f"{where}: profiles[{index}]: "
                f"제품 '{product}'에 해당하는 profiles/{product}/ 디렉터리가 없습니다"
            )
            continue
        for table in profile.tables:
            key = table.name.upper()
            if key in owner:
                problems.append(
                    f"{where}: 테이블 이름 '{table.name}'이(가) 제품 '{owner[key]}'와 "
                    f"'{product}'(profiles/{product}/)에 중복됩니다"
                )
                continue
            owner[key] = product
            tables.append(table)
        glossary.extend(profile.glossary)
        relationships.extend(
            (f"profiles/{product}/product.yml: relationships[{i}]", item)
            for i, item in enumerate(profile.relationships)
        )
        examples.extend(repository.get_examples(product))

    semantic = repository.get_semantic(datasource.id)
    problems.extend(_check_table_data(semantic, tables, datasource.id))
    if len(problems) == before:
        # 앞선 문제(중복된 테이블 등) 때문에 생기는 연쇄 오류로 문제를 늘리지 않는다
        problems.extend(_check_relationships(relationships, tables))

    if len(problems) > before:
        return None
    return ProjectMetadata(
        datasource=datasource,
        tables=tuple(tables),
        table_data=semantic.tables,
        glossary=tuple(glossary),
        examples=tuple(examples),
        relationships=tuple(item for _, item in relationships),
        metadata_version=repository.content_hash(datasource.id),
    )


def _check_table_data(
    semantic: Semantic, tables: list[Table], datasource_id: str
) -> list[str]:
    """semantic의 테이블과 컬럼이 profile에 실제로 있는지 확인한다 (오타나 지워진 컬럼 방지)."""
    columns_of = {
        table.name.upper(): {column.name.upper() for column in table.columns}
        for table in tables
    }
    where = f"semantic/{datasource_id}.json"
    problems: list[str] = []
    for table, rows in semantic.tables.items():
        known = columns_of.get(table.upper())
        if known is None:
            problems.append(
                f"{where}: {table}: profile에 없는 테이블입니다 (이름을 확인하세요)"
            )
            continue
        # 같은 테이블의 모든 행은 같은 컬럼을 갖는다는 검사를 이미 통과했으므로 첫 행만 본다
        problems.extend(
            f"{where}: {table}.{column}: profile에 없는 컬럼입니다 (이름을 확인하세요)"
            for column in rows[0]
            if column.upper() not in known
        )
    return problems


def _check_relationships(
    relationships: list[tuple[str, Relationship]], tables: list[Table]
) -> list[str]:
    """관계의 양쪽 테이블.컬럼이 profile에 실제로 있는지 확인한다."""
    known = {
        f"{table.name}.{column.name}".upper()
        for table in tables
        for column in table.columns
    }
    problems: list[str] = []
    for where, item in relationships:
        for field, ref in (("from", item.source), ("to", item.target)):
            if ref.upper() not in known:
                problems.append(
                    f"{where}.{field}: {ref}은(는) profile에 없는 테이블/컬럼입니다 "
                    f"(이름을 확인하세요)"
                )
    return problems
