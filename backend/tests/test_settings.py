"""TC-68 接口面：新手指引标记 `guide_done` 的契约防护（AC-12 / 开发计划步骤 28）。

前端行为（自动弹出 / 重看 / 不阻塞页面）见测试计划 §3 手工清单；
此处只防护接口层：注册预置 false、写路径回读、StrictBool、账号隔离。
"""

from typing import Any, Callable

API = "/api/v1"


def test_guide_done_default_false(client: Any) -> None:
    """TC-68：注册预置 guide_done=false（新账号首次进首页启动引导的依据）。"""
    data = client.get(f"{API}/settings").json()["data"]
    assert data["guide_done"] is False


def test_guide_done_write_then_readback(client: Any) -> None:
    """TC-68：PUT {guide_done:true} 生效回读；部分更新语义不影响其他键。"""
    before = client.get(f"{API}/settings").json()["data"]
    client.put(f"{API}/settings", json={"guide_done": True})
    after = client.get(f"{API}/settings").json()["data"]
    assert after["guide_done"] is True
    assert after["tts_enabled"] == before["tts_enabled"]
    assert after["default_question_count"] == before["default_question_count"]


def test_guide_done_strict_bool(client: Any) -> None:
    """TC-68：guide_done 传非布尔 → 10001（StrictBool，不做隐式转换）。"""
    resp = client.put(f"{API}/settings", json={"guide_done": "true"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 10001


def test_guide_done_isolated_between_accounts(
    client: Any, make_account: Callable[..., Any]
) -> None:
    """TC-68：A 走完引导不影响 B 的标记（账号级，其他账号不受影响）。"""
    other = make_account("guide_other")
    client.put(f"{API}/settings", json={"guide_done": True})

    a = client.get(f"{API}/settings").json()["data"]
    b = client.get(f"{API}/settings", headers=other["headers"]).json()["data"]
    assert a["guide_done"] is True
    assert b["guide_done"] is False
