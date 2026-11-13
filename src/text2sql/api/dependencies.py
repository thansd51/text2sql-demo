from typing import Annotated

from fastapi import Depends, Request

from text2sql.config import Settings
from text2sql.pipeline import SqlGenerator
from text2sql.semantic import Registry


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


def registry_of(request: Request) -> Registry:
    registry = getattr(request.app.state, "registry", None)
    if registry is None:
        raise RuntimeError(
            "레지스트리가 아직 준비되지 않았습니다 (앱 시작이 끝나지 않음)"
        )
    return registry


def generator_of(request: Request) -> SqlGenerator:
    generator = getattr(request.app.state, "generator", None)
    if generator is None:
        raise RuntimeError(
            "SQL 생성기가 아직 준비되지 않았습니다 (앱 시작이 끝나지 않음)"
        )
    return generator


# 엔드포인트 인자에 쓰는 별칭: `registry: RegistryDep`
RegistryDep = Annotated[Registry, Depends(registry_of)]
GeneratorDep = Annotated[SqlGenerator, Depends(generator_of)]
SettingsDep = Annotated[Settings, Depends(settings_of)]
