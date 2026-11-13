from fastapi import APIRouter

from text2sql.api.dependencies import RegistryDep
from text2sql.api.schemas import DatasourceResponse

router = APIRouter(prefix="/api/v1")


@router.get("/datasources")
def list_datasources(registry: RegistryDep) -> list[DatasourceResponse]:
    return [
        DatasourceResponse(
            id=d.id, name=d.name, db_type=d.db_type, db_version=d.db_version
        )
        for d in registry.datasources()
    ]
