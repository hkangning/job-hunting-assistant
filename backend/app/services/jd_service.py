"""JD 匹配分析业务：prompt 组装、报告落库与分数提取、历史查询（FR-006，接口文档 3.6）。

分层规则（系统设计 3.1）：本层负责业务逻辑与事务边界，不返回 ORM 对象给路由层，出口一律为 schemas 层 DTO。
流式分段本身在路由层用 `utils/section_splitter.py` 完成——本层只管"给 AI 什么"与"拿回来的怎么存"。
"""

import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import BizException, ErrorCode
from app.models import Application, JdAnalysisReport, UserProfile
from app.prompts import build_jd_analysis_messages
from app.schemas.application import JdReportDTO, JdReportListItem
from app.schemas.common import PageData

logger = logging.getLogger(__name__)

# 综合匹配度提取：兼容「综合匹配度：85 分」「**综合匹配度评分**：85」，取 0~100 的整数
_SCORE_PATTERN = re.compile(r"综合匹配度[^\d：:]{0,8}[：:]\s*\**\s*(\d{1,3})")


def build_messages(db: Session, user_id: int, jd_text: str) -> list[dict]:
    """组装 JD 分析对话（FR-006）：当前账号画像摘要 + JD 原文，强制五段结构。"""
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    return build_jd_analysis_messages(profile, jd_text)


def ensure_application(db: Session, user_id: int, application_id: int | None) -> None:
    """校验关联投递的归属：不存在或属于其他账号一律 10002（系统设计 3.6：不暴露存在性）。"""
    if application_id is None:
        return
    exists = db.scalar(
        select(Application.id).where(Application.id == application_id, Application.user_id == user_id)
    )
    if exists is None:
        raise BizException(ErrorCode.NOT_FOUND, "投递记录不存在")


def extract_score(report_text: str) -> int | None:
    """从报告全文提取综合匹配度（TC-20 口径）；未按格式输出或越界时为 null，不算失败。"""
    match = _SCORE_PATTERN.search(report_text)
    if match is None:
        return None
    score = int(match.group(1))
    return score if 0 <= score <= 100 else None


def save_report(
    db: Session,
    user_id: int,
    jd_text: str,
    application_id: int | None,
    report_text: str,
    *,
    is_finished: bool = True,
) -> int | None:
    """落库一份报告（正常完成 is_finished=True / 断连半成品 False，接口文档 3.6）；全空文本不落库、返回 null。"""
    if not report_text.strip():
        logger.warning("JD 分析未产生任何内容，跳过落库（账号 %s）", user_id)
        return None
    report = JdAnalysisReport(
        user_id=user_id,
        application_id=application_id,
        jd_text=jd_text,
        report_text=report_text,
        score=extract_score(report_text),
        is_finished=1 if is_finished else 0,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report.id


def list_reports(
    db: Session,
    *,
    user_id: int,
    application_id: int | None = None,
    page: int = 1,
    page_size: int = 10,
) -> PageData[JdReportListItem]:
    """报告列表：仅当前账号；可按关联投递筛选，按生成时间倒序（company 联表展示）。"""
    conditions = [JdAnalysisReport.user_id == user_id]
    if application_id is not None:
        conditions.append(JdAnalysisReport.application_id == application_id)

    total = db.scalar(select(func.count()).select_from(JdAnalysisReport).where(*conditions)) or 0
    rows = db.execute(
        select(JdAnalysisReport, Application.company)
        .outerjoin(Application, JdAnalysisReport.application_id == Application.id)
        .where(*conditions)
        .order_by(JdAnalysisReport.created_at.desc(), JdAnalysisReport.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PageData[JdReportListItem](
        total=total, items=[_to_list_item(report, company) for report, company in rows]
    )


def get_report(db: Session, user_id: int, report_id: int) -> JdReportDTO:
    """报告详情；不存在或不属于当前账号返回 10002。"""
    report = db.scalar(
        select(JdAnalysisReport).where(
            JdAnalysisReport.id == report_id, JdAnalysisReport.user_id == user_id
        )
    )
    if report is None:
        raise BizException(ErrorCode.NOT_FOUND, "报告不存在")
    return _to_dto(report)


def _to_dto(report: JdAnalysisReport) -> JdReportDTO:
    return JdReportDTO(
        id=report.id,
        application_id=report.application_id,
        jd_text=report.jd_text,
        report_text=report.report_text,
        score=report.score,
        is_finished=bool(report.is_finished),
        created_at=report.created_at,
    )


def _to_list_item(report: JdAnalysisReport, company: str | None) -> JdReportListItem:
    return JdReportListItem(
        id=report.id,
        application_id=report.application_id,
        company=company,
        score=report.score,
        is_finished=bool(report.is_finished),
        created_at=report.created_at,
    )
