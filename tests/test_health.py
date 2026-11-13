from fastapi.testclient import TestClient

from text2sql.config import Settings
from text2sql.main import create_app


def test_health_returns_ok() -> None:
    app = create_app(Settings(_env_file=None))

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
