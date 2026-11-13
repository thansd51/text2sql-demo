"""메타데이터 모델 (docs/design.md "필드 규칙").

파일에서 읽는 모델(DataSource, Profile, ProductExamples, Semantic)은 알 수 없는 키를
거부한다. 철자 오류가 조용히 무시되는 것을 막기 위해서다. 문자열은 엄격하게 받아서
코드 값 같은 숫자가 숫자로 들어오면 오류로 알린다.

테이블과 컬럼 이름은 실제 DB의 이름이다 (OBJ_MAIN, TYPEID, R10_1). 모델도 이 이름으로
SQL을 쓴다.
"""

from collections.abc import Iterable, Iterator
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    field_validator,
    model_validator,
)

# 파일명과 id 형식: [a-z0-9_-]+
ID_PATTERN = r"^[a-z0-9_-]+$"
# 실제 DB의 테이블/컬럼 이름 (대소문자 모두 허용: OBJ_MAIN, R10_1)
PHYSICAL_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"

Id = Annotated[str, StringConstraints(strict=True, pattern=ID_PATTERN)]
PhysicalName = Annotated[
    str, StringConstraints(strict=True, pattern=PHYSICAL_NAME_PATTERN)
]
NonEmptyStr = Annotated[str, StringConstraints(strict=True, min_length=1)]
Text = Annotated[str, StringConstraints(strict=True)]
# 테이블.컬럼 (OBJ_INV.SID)
ColumnRef = Annotated[
    str,
    StringConstraints(
        strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$"
    ),
]

DbType = Literal["oracle", "postgresql"]
DEFAULT_PROFILES = ("innoproduct",)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"{label}이(가) 중복됩니다: {value}")
        seen.add(value)


class DataSource(_Model):
    """datasources/<id>.json. 데이터소스는 DB 하나를 뜻한다."""

    id: Id
    name: NonEmptyStr
    db_type: DbType
    db_version: NonEmptyStr
    profiles: tuple[Id, ...] = DEFAULT_PROFILES

    @field_validator("profiles")
    @classmethod
    def _profiles_not_empty_or_duplicated(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not value:
            raise ValueError("profiles에는 제품이 1개 이상 있어야 합니다")
        _check_unique(value, "제품 이름")
        return value


class Column(_Model):
    name: PhysicalName
    type: NonEmptyStr
    description: Text = ""
    synonyms: tuple[NonEmptyStr, ...] = ()


class Table(_Model):
    """실제 DB 테이블 하나. 컬럼 설명은 여기에 한 번만 적는다."""

    name: PhysicalName
    description: Text = ""
    # 업무 영역(상품, 계약 등). 테이블이 많아졌을 때 후보를 좁히는 데 쓴다 (선택)
    group: Text = ""
    # 이 테이블을 쓸 때 지켜야 할 사용 규칙. 스키마에서 이 테이블 바로 아래에 보여 준다
    rules: tuple[NonEmptyStr, ...] = ()
    # 이 테이블 행의 "이름"이 들어 있는 컬럼 (예: OBJ_NAME)과, 그 행을 조회할 때 조건으로 쓰는
    # 컬럼들 (예: TYPEID, R10_1). 둘 다 지정하면 프롬프트에서 semantic의 행을
    # "이름: 그 행을 가리키는 조건"으로 보여 준다. 질문에 이름이 나올 때 이름 문자열로
    # 비교하지 않고 같은 행의 코드로 조회하게 하려는 것이다.
    name_column: PhysicalName | None = None
    key_columns: tuple[PhysicalName, ...] = ()
    columns: tuple[Column, ...]

    @field_validator("columns")
    @classmethod
    def _columns_valid(cls, value: tuple[Column, ...]) -> tuple[Column, ...]:
        if not value:
            raise ValueError("columns에는 컬럼이 1개 이상 있어야 합니다")
        _check_unique((column.name.upper() for column in value), "컬럼 이름")
        return value

    @model_validator(mode="after")
    def _lookup_columns_exist(self) -> "Table":
        known = {column.name.upper() for column in self.columns}
        if self.name_column is not None and self.name_column.upper() not in known:
            raise ValueError(
                f"name_column '{self.name_column}'이(가) 이 테이블의 컬럼에 없습니다"
            )
        for key in self.key_columns:
            if key.upper() not in known:
                raise ValueError(
                    f"key_columns '{key}'이(가) 이 테이블의 컬럼에 없습니다"
                )
        _check_unique((key.upper() for key in self.key_columns), "key_columns")
        return self


class Example(_Model):
    question: NonEmptyStr
    # 기본 문법으로 쓴다. 행 제한과 날짜 함수는 쓰지 않는다.
    sql: NonEmptyStr


class Relationship(_Model):
    """테이블 사이의 조인 키 하나. `from`과 `to`는 테이블.컬럼이다."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    source: ColumnRef = Field(alias="from")
    target: ColumnRef = Field(alias="to")
    note: Text = ""

    def render(self) -> str:
        line = f"{self.source} = {self.target}"
        return f"{line} ({self.note})" if self.note else line


class ProductFile(_Model):
    """profiles/<제품>/product.yml. 제품 공통의 관계와 용어집 (테이블은 tables/ 아래 파일)."""

    product: Id
    relationships: tuple[Relationship, ...] = ()
    glossary: tuple[NonEmptyStr, ...] = ()


class Profile(_Model):
    """profiles/<제품>/ 디렉터리 전체를 모은 제품 공통 정의.

    product.yml과 tables/<테이블>.yml들을 읽어서 만든다 (파일 하나가 테이블 하나).
    """

    product: Id
    tables: tuple[Table, ...]
    relationships: tuple[Relationship, ...] = ()
    glossary: tuple[NonEmptyStr, ...] = ()

    @field_validator("tables")
    @classmethod
    def _tables_valid(cls, value: tuple[Table, ...]) -> tuple[Table, ...]:
        if not value:
            raise ValueError("tables에는 테이블이 1개 이상 있어야 합니다")
        _check_unique((table.name.upper() for table in value), "테이블 이름")
        return value


class ProductExamples(_Model):
    """examples/<제품>.yml. 그 제품을 쓰는 모든 프로젝트가 함께 쓰는 질문-SQL 예시."""

    product: Id
    examples: tuple[Example, ...] = ()


# 행 하나: {컬럼: 값}. 테이블 정의(profile)의 컬럼을 모두 적고, 값이 없는 컬럼은 ""로 둔다
# (null은 쓰지 않는다). 숫자도 문자열로 쓴다 ("101"). 테이블이 달라도 같은 이름의 컬럼이 FK로
# 이어진다는 점은 profile의 relationships가 알려 준다.
RowValue = Annotated[str, StringConstraints(strict=True)]
Row = dict[PhysicalName, RowValue]


def _check_rows(value: tuple[Row, ...]) -> tuple[Row, ...]:
    if not value:
        raise ValueError("행이 1개 이상 있어야 합니다")
    columns = [{name.upper() for name in row} for row in value]
    for row in value:
        _check_unique((name.upper() for name in row), "컬럼 이름")
        if not row:
            raise ValueError("행에는 컬럼이 1개 이상 있어야 합니다")
    for index, names in enumerate(columns[1:], start=1):
        if names != columns[0]:
            raise ValueError(
                f"{index}번째 행의 컬럼이 첫 행과 다릅니다. 같은 테이블의 모든 행에 같은 "
                '컬럼을 적고, 값이 없으면 ""로 두세요'
            )
    seen: set[tuple[tuple[str, str], ...]] = set()
    for row in value:
        key = tuple(sorted((name.upper(), item) for name, item in row.items()))
        if key in seen:
            raise ValueError("같은 행이 두 번 적혀 있습니다")
        seen.add(key)
    return value


# 한 테이블의 행들. 같은 테이블의 모든 행은 같은 컬럼을 갖는다.
TableRows = Annotated[tuple[Row, ...], AfterValidator(_check_rows)]
# {테이블: [행...]}. 실제 DB의 테이블 데이터(코드 값과 그 이름 등)다.
# 같은 코드도 프로젝트마다 이름이 다를 수 있어서 프로젝트별 semantic에 둔다.
TableData = dict[PhysicalName, TableRows]


def _check_table_names(value: TableData) -> TableData:
    _check_unique((table.upper() for table in value), "테이블 이름")
    return value


def iter_rows(data: TableData) -> Iterator[tuple[str, Row]]:
    """(테이블, 행)을 파일에 적힌 순서대로 돌려준다."""
    for table, rows in data.items():
        for row in rows:
            yield table, row


class Semantic(RootModel[Annotated[TableData, AfterValidator(_check_table_names)]]):
    """semantic/<id>.json. 프로젝트마다 다른 테이블 데이터. 파일 최상위가 바로 테이블이다.

    예: {"OBJ_MAIN": [{"TYPEID": "101", "OBJ_NAME": "장기상품", "R10_1": ""}]}
    """

    model_config = ConfigDict(frozen=True)

    @property
    def tables(self) -> TableData:
        return self.root


class ProjectMetadata(_Model):
    """레지스트리에 저장하는, 데이터소스 하나의 완성된 메타데이터.

    profile들을 병합하고 공통 예시와 semantic을 더한 결과다. 파이프라인은 이것만 본다.
    """

    datasource: DataSource
    tables: tuple[Table, ...]
    table_data: TableData = Field(default_factory=dict)
    glossary: tuple[str, ...] = ()
    examples: tuple[Example, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    # 파일 내용 해시. 응답의 metadata_version이다.
    metadata_version: str

    def table_names(self) -> set[str]:
        """검증의 허용 테이블 목록."""
        return {table.name for table in self.tables}

    def columns_by_table(self) -> dict[str, list[str]]:
        """1차 검증의 allowed_columns로 넘기는 {테이블: 컬럼들}."""
        return {
            table.name: [column.name for column in table.columns]
            for table in self.tables
        }

    def get_table(self, name: str) -> Table | None:
        return next((t for t in self.tables if t.name.upper() == name.upper()), None)
