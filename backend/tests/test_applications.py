"""投递模块测试：服务层 TC-01~04 + API 集成 TC-26 / TC-46（接口文档 3.3）。"""

from datetime import date, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import BizException, ErrorCode
from app.models import Application, InterviewSession, JdAnalysisReport
from app.models.enums import ApplicationStatus
from app.schemas.application import ApplicationCreate, ApplicationStatusUpdate
from app.services import application_service

API = "/api/v1/applications"


def _xlsx(rows: list[list]) -> bytes:
    """把若干行（首行为表头）组装成 xlsx 字节流，供导入用例使用。"""
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ---------- TC-01 新增投递 ----------


def test_create_application_defaults(db_session: Session):
    """TC-01：字段合法入库，status 默认 APPLIED，投递日期默认当天。"""
    dto = application_service.create_application(
        db_session,
        ApplicationCreate(company="浩鲸科技", position="Java 开发", city="南京", expected_salary="13k", channel="官网"),
    )

    assert dto.id > 0
    assert dto.status == ApplicationStatus.APPLIED
    assert dto.applied_at == date.today()
    assert (dto.company, dto.position, dto.city) == ("浩鲸科技", "Java 开发", "南京")

    row = db_session.get(Application, dto.id)
    assert row is not None and row.status == "APPLIED"


# ---------- TC-02 状态流转 ----------


def test_change_status_legal_chain(db_session: Session):
    """TC-02：合法流转链 APPLIED→WRITTEN→INTERVIEW→OFFER 逐跳成功。"""
    dto = application_service.create_application(
        db_session, ApplicationCreate(company="浩鲸科技", position="Java 开发")
    )

    for target in (ApplicationStatus.WRITTEN, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER):
        dto = application_service.change_status(db_session, dto.id, ApplicationStatusUpdate(status=target))
        assert dto.status == target


@pytest.mark.parametrize(
    "start",
    [ApplicationStatus.APPLIED, ApplicationStatus.WRITTEN, ApplicationStatus.INTERVIEW],
)
def test_change_status_closed_from_any_active_state(db_session: Session, start: ApplicationStatus):
    """TC-02：任意非终态均可流转至 CLOSED。"""
    dto = application_service.create_application(
        db_session, ApplicationCreate(company="亚信科技", position="后端开发", status=start)
    )

    dto = application_service.change_status(
        db_session, dto.id, ApplicationStatusUpdate(status=ApplicationStatus.CLOSED)
    )

    assert dto.status == ApplicationStatus.CLOSED


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW),  # 跳级
        (ApplicationStatus.APPLIED, ApplicationStatus.OFFER),  # 跳级
        (ApplicationStatus.APPLIED, ApplicationStatus.APPLIED),  # 原地不动
        (ApplicationStatus.OFFER, ApplicationStatus.CLOSED),  # 终态不可再流转
        (ApplicationStatus.CLOSED, ApplicationStatus.WRITTEN),
    ],
)
def test_change_status_illegal_rejected(db_session: Session, start: ApplicationStatus, target: ApplicationStatus):
    """TC-02：非法流转拒绝（错误码 10001），且库中状态不变。"""
    dto = application_service.create_application(
        db_session,
        ApplicationCreate(company="新华三", position="Java 开发", status=start),
    )

    with pytest.raises(BizException) as exc_info:
        application_service.change_status(db_session, dto.id, ApplicationStatusUpdate(status=target))

    assert exc_info.value.code == ErrorCode.PARAM_INVALID
    db_session.expire_all()
    assert db_session.get(Application, dto.id).status == start


def test_change_status_event_and_remark_appended(db_session: Session):
    """TC-02：转 WRITTEN/INTERVIEW 时更新下次考试时间，流转备注追加不覆盖原备注。"""
    event_at = f"{date.today() + timedelta(days=3)} 14:00:00"
    dto = application_service.create_application(
        db_session, ApplicationCreate(company="满帮", position="Java 开发", remark="原备注")
    )

    dto = application_service.change_status(
        db_session,
        dto.id,
        ApplicationStatusUpdate(status=ApplicationStatus.WRITTEN, event_at=event_at, remark="收到笔试通知"),
    )

    assert dto.next_event_at.strftime("%Y-%m-%d %H:%M:%S") == event_at
    assert dto.remark.startswith("原备注\n[")
    assert "流转至 待笔试] 收到笔试通知" in dto.remark


# ---------- TC-03 批量导入（行级容错） ----------


def test_import_xlsx_partial_rows(db_session: Session):
    """TC-03：xlsx 合法行入库，非法行只记错误不中断其余行。"""
    content = _xlsx(
        [
            ["company", "position", "city", "applied_at", "channel", "status", "remark"],
            ["浩鲸科技", "Java 开发", "南京", "2026-09-01", "官网", "APPLIED", "已投"],
            ["", "前端开发", "南京", "2026-09-02", "BOSS", "APPLIED", ""],  # 公司为空
            ["亚信科技", "后端开发", "上海", "2026-09-03", "内推", "WRITTEN", ""],
        ]
    )

    result = application_service.import_from_file(db_session, "投递清单.xlsx", content)

    assert result.success_count == 2
    assert [(item.row, item.reason) for item in result.errors] == [(3, "公司名称不能为空")]
    imported = {row.company: row.status for row in db_session.scalars(select(Application)).all()}
    assert imported == {"浩鲸科技": "APPLIED", "亚信科技": "WRITTEN"}


def test_import_csv_partial_rows(db_session: Session):
    """TC-03：csv（GBK 编码）解析成功；非法状态与非法日期进 errors，空白行跳过。"""
    content = (
        "company,position,applied_at,status\n"
        "云器科技,Java 开发,2026/09/01,\n"  # 日期用 / 分隔可解析，状态空走默认
        "合合信息,,2026-09-02,APPLIED\n"  # 岗位为空
        ",,,\n"  # 整行空白：跳过
        "哈啰出行,后端开发,9月3日,APPLIED\n"  # 日期格式非法
        "招银网络,后端开发,2026-09-04,UNKNOWN\n"  # 状态非法
    ).encode("gbk")

    result = application_service.import_from_file(db_session, "import.csv", content)

    assert result.success_count == 1
    assert [(item.row, item.reason) for item in result.errors] == [
        (3, "岗位名称不能为空"),
        (5, "投递日期格式应为 YYYY-MM-DD"),
        (6, "状态值非法（可选：APPLIED/WRITTEN/INTERVIEW/OFFER/CLOSED）"),
    ]


def test_import_all_rows_invalid_raises_20002(db_session: Session):
    """TC-03：全部行非法时不入库，返回 20002 并携带行级清单。"""
    content = "company,position\n,Java\n,后端\n".encode("utf-8")

    with pytest.raises(BizException) as exc_info:
        application_service.import_from_file(db_session, "import.csv", content)

    assert exc_info.value.code == ErrorCode.IMPORT_ROW_INVALID
    assert exc_info.value.data["success_count"] == 0
    assert [item["row"] for item in exc_info.value.data["errors"]] == [2, 3]
    assert db_session.query(Application).count() == 0


# ---------- TC-04 文件与表头校验 ----------


def test_import_missing_required_header(db_session: Session):
    """TC-04：表头缺少必填列（position）→ 20001。"""
    with pytest.raises(BizException) as exc_info:
        application_service.import_from_file(db_session, "import.csv", b"company,city\nA,\xe5\x8d\x97\xe4\xba\xac\n")

    assert exc_info.value.code == ErrorCode.IMPORT_FILE_INVALID
    assert "position" in exc_info.value.message


def test_import_empty_header(db_session: Session):
    """TC-04：没有表头行（空文件）→ 20001。"""
    with pytest.raises(BizException) as exc_info:
        application_service.import_from_file(db_session, "import.csv", b"\n")

    assert exc_info.value.code == ErrorCode.IMPORT_FILE_INVALID


def test_import_unsupported_file_type(db_session: Session):
    """TC-04：扩展名非 xlsx/csv → 20001。"""
    with pytest.raises(BizException) as exc_info:
        application_service.import_from_file(db_session, "import.pdf", b"whatever")

    assert exc_info.value.code == ErrorCode.IMPORT_FILE_INVALID


# ---------- 删除的引用维护 ----------


def test_delete_application_detaches_related_records(db_session: Session):
    """删除投递：关联 JD 报告/面试会话保留数据、解除关联（否则外键拦截删除会 500）。"""
    dto = application_service.create_application(
        db_session, ApplicationCreate(company="云器科技", position="后端开发")
    )
    report = JdAnalysisReport(application_id=dto.id, jd_text="JD 原文", report_text="五段报告")
    session = InterviewSession(application_id=dto.id, company="云器科技", position="后端开发")
    db_session.add_all([report, session])
    db_session.commit()

    application_service.delete_application(db_session, dto.id)

    db_session.expire_all()
    assert db_session.get(Application, dto.id) is None
    assert db_session.get(JdAnalysisReport, report.id).application_id is None
    assert db_session.get(InterviewSession, session.id).application_id is None


# ---------- TC-26 投递 CRUD 全流程（API 集成） ----------


def test_application_crud_flow(client: TestClient):
    """TC-26：创建→详情→编辑→列表筛选分页→删除→404，全链路走接口文档口径。"""
    created = client.post(
        API,
        json={
            "company": "浩鲸科技",
            "position": "Java 开发",
            "city": "南京",
            "expected_salary": "13k",
            "applied_at": "2026-09-20",
            "channel": "官网",
            "remark": "面试已过 BP 面",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["code"] == 0 and body["message"] == "ok"
    app_id = body["data"]["id"]
    assert body["data"]["status"] == "APPLIED"
    assert body["data"]["applied_at"] == "2026-09-20"
    assert body["data"]["created_at"].count(":") == 2 and "T" not in body["data"]["created_at"]

    # 详情：含备注全文
    detail = client.get(f"{API}/{app_id}").json()["data"]
    assert detail["remark"] == "面试已过 BP 面"

    # 编辑（全量更新：未传字段置空，status 不受影响）
    updated = client.put(
        f"{API}/{app_id}",
        json={"company": "浩鲸科技国际", "position": "Java 开发", "status": "OFFER"},
    ).json()["data"]
    assert updated["company"] == "浩鲸科技国际"
    assert updated["city"] is None and updated["expected_salary"] is None
    assert updated["applied_at"] == date.today().isoformat()  # 未传投递日期 → 默认当天
    assert updated["status"] == "APPLIED"  # status 只能走流转接口

    # 状态流转
    patched = client.patch(
        f"{API}/{app_id}/status", json={"status": "WRITTEN", "event_at": "2026-09-26 14:00:00", "remark": "笔试通知"}
    ).json()["data"]
    assert patched["status"] == "WRITTEN"
    assert patched["next_event_at"] == "2026-09-26 14:00:00"

    # 列表：筛选 + 分页 + 列表项不含 remark
    listed = client.get(API, params={"status": "WRITTEN", "company": "浩鲸", "page": 1, "page_size": 10}).json()
    assert listed["data"]["total"] == 1
    assert "remark" not in listed["data"]["items"][0]
    assert client.get(API, params={"status": "OFFER"}).json()["data"]["total"] == 0
    assert client.get(API, params={"page_size": 51}).json()["code"] == 10001  # 分页上限 50

    # 删除 → 详情 404
    assert client.delete(f"{API}/{app_id}").json() == {"code": 0, "message": "ok", "data": None}
    assert client.get(f"{API}/{app_id}").json()["code"] == 10002


def test_application_invalid_payload(client: TestClient):
    """TC-26：必填字段缺失/超长 → 参数校验失败 10001。"""
    assert client.post(API, json={"position": "Java 开发"}).json()["code"] == 10001
    assert client.post(API, json={"company": "  ", "position": "Java 开发"}).json()["code"] == 10001
    assert client.post(API, json={"company": "A" * 101, "position": "Java"}).json()["code"] == 10001
    assert client.get(f"{API}/9999999").json()["code"] == 10002


def test_import_endpoints_api(client: TestClient):
    """TC-26：模板下载返回 xlsx 文件流；上传导入成功与全非法（20002 带行级清单）。"""
    template = client.get(f"{API}/template")
    assert template.status_code == 200
    assert template.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "application_import_template.xlsx" in template.headers["content-disposition"]
    assert template.content[:2] == b"PK"  # xlsx 即 zip 包

    ok = client.post(
        f"{API}/import",
        files={"file": ("投递清单.xlsx", _xlsx([["company", "position"], ["满帮", "Java 开发"]]), "application/vnd.ms-excel")},
    ).json()
    assert ok["code"] == 0
    assert ok["data"] == {"success_count": 1, "errors": []}

    bad = client.post(f"{API}/import", files={"file": ("bad.csv", b"company,position\n,Java\n", "text/csv")})
    assert bad.status_code == 400
    assert bad.json()["code"] == 20002
    assert bad.json()["data"]["errors"][0] == {"row": 2, "reason": "公司名称不能为空"}


# ---------- TC-46 投递趋势 ----------


def test_trend_zero_filled_and_bounds(client: TestClient):
    """TC-46：按日 GROUP BY 计数、补齐 0 值日期、days 边界（默认 30 / 上限 90）。"""
    today = date.today()
    yesterday = today - timedelta(days=1)
    for company, applied in (("A 公司", today), ("B 公司", today), ("C 公司", yesterday)):
        client.post(API, json={"company": company, "position": "Java 开发", "applied_at": applied.isoformat()})

    items = client.get(f"{API}/trend", params={"days": 7}).json()["data"]["items"]
    assert len(items) == 7
    assert items[0]["date"] == (today - timedelta(days=6)).isoformat()
    assert items[-1] == {"date": today.isoformat(), "count": 2}
    assert items[-2]["count"] == 1
    assert items[0]["count"] == 0  # 无投递日期补 0

    assert len(client.get(f"{API}/trend").json()["data"]["items"]) == 30  # 默认 30 天
    assert client.get(f"{API}/trend", params={"days": 90}).json()["code"] == 0
    assert client.get(f"{API}/trend", params={"days": 91}).json()["code"] == 10001
    assert client.get(f"{API}/trend", params={"days": 0}).json()["code"] == 10001
