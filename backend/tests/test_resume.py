"""简历解析服务用例（步骤 27 覆盖率补齐；FR-012 / 接口文档 §3.12）。

覆盖 `resume_service` 此前未测的分支：文件校验（扩展名 / 空内容 / 超限）三分支、
PDF 与 Word 提取（含表格排版）、`_tidy` 压空行、AI 抽取的成功与全部降级路径、
字段清洗与经历条目清洗的全部分支。文件资产在进程内构造（docx 用 python-docx 写、
PDF 为手写最小单页），不依赖外部夹具。
"""

import io

import docx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.exceptions import BizException
from app.models import LlmProviderConfig
from app.services.resume_service import (
    MAX_RESUME_BYTES,
    _as_text,
    _clean,
    _clean_experiences,
    _extract_docx,
    _extract_pdf,
    _suffix,
    _tidy,
    parse_resume,
)

RESUME_API = "/api/v1/profile/resume"


def _docx_bytes(paragraphs=("张三", "南京理工大学 计算机专业"), table_rows=(("项目", "企业管理系统"),)) -> bytes:
    """构造一份带段落 + 表格的 docx（表格是简历常用排版，覆盖表格提取分支）。"""
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table_rows:
        table = document.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for r, row in enumerate(table_rows):
            for c, cell in enumerate(row):
                table.cell(r, c).text = cell
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _minimal_pdf(text: str = "Resume Pdf Text") -> bytes:
    """手写最小单页 PDF（Helvetica 文本层）——仅用于覆盖 PDF 文字提取路径。"""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return bytes(out)


# ================================================================ 文件校验


class TestFileValidation:
    def test_unsupported_extension(self, db_session: Session, account_id: int, fake_llm_client):
        with pytest.raises(BizException) as exc:
            parse_resume(
                db_session, user_id=account_id, filename="resume.txt",
                content=b"hello", client=fake_llm_client,
            )
        assert exc.value.code == 10001

    def test_extension_case_insensitive(self, db_session: Session, account_id: int, fake_llm_client):
        """扩展名大小写不敏感（.DOCX 合法）——内容不可解析时才走到解析错误分支。"""
        with pytest.raises(BizException) as exc:
            parse_resume(
                db_session, user_id=account_id, filename="RESUME.DOCX",
                content=b"not a real docx", client=fake_llm_client,
            )
        assert "Word" in exc.value.message

    def test_empty_content(self, db_session: Session, account_id: int, fake_llm_client):
        with pytest.raises(BizException) as exc:
            parse_resume(
                db_session, user_id=account_id, filename="a.docx",
                content=b"", client=fake_llm_client,
            )
        assert exc.value.message == "文件内容为空"

    def test_oversize_rejected_before_parse(self, db_session: Session, account_id: int, fake_llm_client):
        with pytest.raises(BizException) as exc:
            parse_resume(
                db_session, user_id=account_id, filename="a.pdf",
                content=b"x" * (MAX_RESUME_BYTES + 1), client=fake_llm_client,
            )
        assert exc.value.message == "文件不能超过 10MB"

    def test_suffix_helper(self):
        assert _suffix("A.PDF") == ".pdf"
        assert _suffix("  b.Docx ") == ".docx"
        assert _suffix("noext") == ""
        assert _suffix("") == ""


# ================================================================ 文本提取


class TestExtraction:
    def test_docx_paragraphs_and_tables(self):
        text = _extract_docx(_docx_bytes())
        assert "张三" in text
        assert "企业管理系统" in text  # 表格内容不漏
        assert " | " in text  # 表格按行拼接

    def test_docx_corrupt_raises_param_invalid(self):
        with pytest.raises(BizException) as exc:
            _extract_docx(b"definitely not a zip")
        assert "Word" in exc.value.message

    def test_pdf_extracts_text_layer(self):
        text = _extract_pdf(_minimal_pdf("Hello Resume"))
        assert "Hello Resume" in text

    def test_pdf_corrupt_raises_param_invalid(self):
        with pytest.raises(BizException) as exc:
            _extract_pdf(b"%PDF-1.4 but broken")
        assert "PDF 解析失败" in exc.value.message

    def test_tidy_collapses_blank_lines(self):
        raw = "第一行  \r\n\r\n\r\n第二行\n\n  \n第三行  "
        assert _tidy(raw) == "第一行\n\n第二行\n\n第三行"

    def test_pdf_without_text_layer_rejected(self, db_session: Session, account_id: int, fake_llm_client):
        """无文字层的 PDF（全空内容）→ 10001（扫描件提示）。"""
        with pytest.raises(BizException) as exc:
            parse_resume(
                db_session, user_id=account_id, filename="scan.pdf",
                content=_minimal_pdf(""), client=fake_llm_client,
            )
        assert "未能从文件中提取到文字" in exc.value.message


# ================================================================ AI 抽取与降级


def _configure_llm(db: Session, user_id: int) -> None:
    """给服务层用例的账号配一个供应商（同 conftest.llm_configured，但作用于 db_session 账号）。"""
    from app.utils.security import encrypt_text

    db.add(
        LlmProviderConfig(
            user_id=user_id,
            provider="deepseek",
            api_key=encrypt_text("sk-test"),
            model="test-model",
            is_active=1,
        )
    )
    db.commit()


class TestAiExtraction:
    def test_extract_success_returns_cleaned_fields(self, db_session: Session, account_id: int, fake_llm_client):
        _configure_llm(db_session, account_id)
        fake_llm_client.json_result = {
            "name": " 张三 ",
            "school": "南京理工大学",
            "skills": ["Java", "Java", "MySQL", ""],
            "experiences": [
                {"type": "project", "title": " 企业管理系统 ", "org": "某公司"},
                {"type": "UNKNOWN", "title": "应被丢弃"},
                {"type": "INTERNSHIP"},  # 无 title，丢弃
            ],
        }
        data = parse_resume(
            db_session, user_id=account_id, filename="a.docx",
            content=_docx_bytes(), client=fake_llm_client,
        )
        assert data.extracted.name == "张三"  # strip 生效
        assert data.extracted.skills == ["Java", "MySQL"]  # 去重 + 空项过滤
        assert len(data.extracted.experiences) == 1  # 非法 type / 无 title 的条目被丢
        assert data.extracted.experiences[0].title == "企业管理系统"

    def test_llm_error_degrades_to_null(self, db_session: Session, account_id: int, fake_llm_client):
        """模型调用失败（10011 类）→ extracted=null、不抛错（前端提示手填）。"""
        fake_llm_client.error = RuntimeError("chat_json 失败")
        data = parse_resume(
            db_session, user_id=account_id, filename="a.docx",
            content=_docx_bytes(), client=fake_llm_client,
        )
        assert data.extracted is None

    def test_llm_not_configured_degrades_to_null(self, db_session: Session, account_id: int, fake_llm_client):
        """未配 AI（resolve_config 抛 10012）→ 同样降级 null（不依赖 llm_configured fixture）。"""
        data = parse_resume(
            db_session, user_id=account_id, filename="a.docx",
            content=_docx_bytes(), client=fake_llm_client,
        )
        assert data.extracted is None

    def test_empty_ai_result_returns_null(self, db_session: Session, account_id: int, fake_llm_client):
        """模型输出全空字段 → 清洗后全空 → extracted=null。"""
        _configure_llm(db_session, account_id)
        fake_llm_client.json_result = {"name": "", "skills": [], "experiences": []}
        data = parse_resume(
            db_session, user_id=account_id, filename="a.docx",
            content=_docx_bytes(), client=fake_llm_client,
        )
        assert data.extracted is None


# ================================================================ 清洗纯函数


class TestClean:
    def test_field_truncation_and_number_coercion(self):
        cleaned = _clean({"name": "x" * 100, "gpa": 3.6})
        assert len(cleaned.name) == 50  # name 上限 50
        assert cleaned.gpa == "3.6"  # 数字转文本

    def test_skills_limit_and_dedupe(self):
        cleaned = _clean({"skills": [f"skill{i}" for i in range(30)] + ["skill0"]})
        assert len(cleaned.skills) == 20  # _SKILLS_MAX

    def test_all_empty_returns_none(self):
        assert _clean({}) is None
        assert _clean({"name": " ", "skills": ["", None]}) is None

    def test_as_text_rules(self):
        assert _as_text("  a ") == "a"
        assert _as_text(42) == "42"
        assert _as_text(True) == ""  # 布尔不是文本
        assert _as_text(None) == ""
        assert _as_text(["x"]) == ""

    def test_clean_experiences_branches(self):
        assert _clean_experiences(None) is None  # 非 list
        assert _clean_experiences([]) is None  # 空列表
        assert _clean_experiences([{"type": "PROJECT"}]) is None  # 无 title
        many = [{"type": "PROJECT", "title": f"t{i}"} for i in range(12)]
        assert len(_clean_experiences(many)) == 10  # 上限 10 条
        long = _clean_experiences([{"type": "CAMPUS", "title": "t", "description": "d" * 3000}])
        assert len(long[0].description) == 2000  # description 上限


# ================================================================ API 链路


class TestResumeApi:
    def test_unsupported_type_400(self, client: TestClient, account):
        resp = client.post(
            RESUME_API,
            files={"file": ("resume.txt", b"hello", "text/plain")},
            headers={"Authorization": f"Bearer {account['token']}"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 10001

    def test_docx_without_ai_returns_null_extracted(self, client: TestClient, account):
        """未配 AI 上传合法 docx → 200 + extracted=null（不报错，前端提示手填）。"""
        resp = client.post(
            RESUME_API,
            files={"file": ("resume.docx", _docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            headers={"Authorization": f"Bearer {account['token']}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["extracted"] is None

    def test_docx_with_ai_extracts(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """配好 AI：同一文件走到抽取成功路径，字段回传。"""
        fake_llm_client.json_result = {"name": "李四", "school": "东南大学"}
        resp = client.post(
            RESUME_API,
            files={"file": ("resume.docx", _docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            headers={"Authorization": f"Bearer {account['token']}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["extracted"]["name"] == "李四"
