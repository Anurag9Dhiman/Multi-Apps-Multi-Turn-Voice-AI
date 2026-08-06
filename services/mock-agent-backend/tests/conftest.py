import pytest
from fastapi.testclient import TestClient

from mock_agent_backend.app import app
from mock_agent_backend.session import STORE


@pytest.fixture()
def client():
    STORE.tasks_by_user.clear()
    with TestClient(app) as c:
        yield c
