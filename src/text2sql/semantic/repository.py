"""프로젝트 데이터 저장소 인터페이스.

파이프라인은 이 인터페이스(와 레지스트리)에만 의존한다. 현재 구현은 파일이고
(file_repository.FileRepository), 후속에 DB 구현으로 교체한다.
"""

from typing import Protocol

from text2sql.semantic.models import DataSource, Example, Profile, Semantic


class SemanticRepository(Protocol):
    def get_datasource(self, datasource_id: str) -> DataSource | None:
        """등록된 데이터소스를 돌려준다. 없으면 None."""
        ...

    def list_datasources(self) -> list[DataSource]:
        """등록된 모든 데이터소스. id 순서."""
        ...

    def get_semantic(self, datasource_id: str) -> Semantic:
        """프로젝트마다 다른 값. 없으면 빈 Semantic을 돌려준다 (semantic은 선택이다)."""
        ...

    def get_profile(self, product: str) -> Profile | None:
        """제품 공통 정의. 없으면 None."""
        ...

    def get_examples(self, product: str) -> tuple[Example, ...]:
        """제품 공통 질문-SQL 예시. 없으면 빈 튜플 (예시는 선택이다)."""
        ...

    def content_hash(self, datasource_id: str) -> str:
        """이 데이터소스를 이루는 원본 내용(데이터소스, 사용하는 제품의 profile과 예시, semantic)의 해시.

        내용이 바뀌면 값이 바뀐다. 다른 데이터소스의 내용은 영향을 주지 않는다.
        """
        ...
