"""骨架阶段测试：健康检查 + 统一响应体四态（TC-25）。"""

from fastapi import Query
from fastapi.testclient import TestClient

from app.exceptions import BizException, ErrorCode
from app.schemas.common import ApiResponse


def test_health_ok(client: TestClient):
    """健康检查成功态：响应体结构完整且**不含任何账号信息**（免鉴权接口）。"""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "code": 0,
        "message": "ok",
        "data": {"status": "ok"},
    }


def test_health_has_no_account_info(client: TestClient):
    """回归防护：原 `llm_configured` 字段随多账号改造移出健康检查（改由 GET /auth/me 按账号返回）。"""
    resp = client.get("/api/v1/health")
    assert "llm_configured" not in resp.json()["data"]
    assert "user" not in resp.json()["data"]


def test_response_param_invalid(client: TestClient):
    """四态之二：参数校验失败 → 400 + 10001，message 带字段名。"""

    @client.app.get("/api/v1/_test/validate")
    def _validate(n: int = Query(...)):
        return ApiResponse()

    resp = client.get("/api/v1/_test/validate", params={"n": "abc"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 10001
    assert "n" in body["message"]


def test_response_not_found(client: TestClient):
    """四态之三：路由不存在 → 404 + 10002。"""
    resp = client.get("/api/v1/_test/not-exist")
    assert resp.status_code == 404
    assert resp.json()["code"] == 10002


def test_response_biz_exception(client: TestClient):
    """业务异常：按错误码映射 HTTP 状态与默认文案。"""

    @client.app.get("/api/v1/_test/biz")
    def _biz():
        raise BizException(ErrorCode.WRONG_QUESTION_INVALID)

    resp = client.get("/api/v1/_test/biz")
    assert resp.status_code == 404
    assert resp.json() == {"code": 30002, "message": "错题不存在或已掌握", "data": None}


def test_response_internal_error(client: TestClient):
    """四态之四：未捕获异常 → 500 + 10000，响应不含堆栈。"""

    @client.app.get("/api/v1/_test/boom")
    def _boom():
        raise RuntimeError("boom")

    resp = client.get("/api/v1/_test/boom")
    assert resp.status_code == 500
    assert resp.json() == {"code": 10000, "message": "系统内部错误", "data": None}
