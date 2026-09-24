"""pytest 公共 fixture：TestClient 与 AI mock 注入点（测试计划 1.3）。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    """TestClient：关闭异常抛出，便于断言 500 场景的统一响应体。"""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
