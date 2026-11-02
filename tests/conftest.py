import pytest
from fastapi.testclient import TestClient
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.storage.database import Database


@pytest.fixture
def client(tmp_path):
    db = Database(tmp_path / "test.db")
    cfg = Settings(_env_file=None,llm_base_url="",llm_model="",llm_api_key="",data_dir=tmp_path)
    app = create_app(config=cfg,db=db,run_worker=False)
    with TestClient(app,base_url="http://127.0.0.1") as client:
        yield client
    db.close()
