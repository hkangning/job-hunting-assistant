"""八股陪练接口：元数据 / 抽题 / 训练会话 / 掌握度（接口文档 3.8）。

路由层只做协议转换（系统设计 3.1）：参数校验、调服务层、包统一响应体，不直接访问 ORM。
每轮的**内容产出**走流式端点 `POST /stream/practice-turn`（见 routers/stream.py），本模块只落 REST 部分。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models.enums import PracticeMode, Stack
from app.schemas.common import ApiResponse, PageData
from app.schemas.practice import (
    MasteryData,
    PracticeMetaDTO,
    QuestionListData,
    QuestionPickRequest,
    SessionCreateData,
    SessionCreateRequest,
    SessionDetailData,
    SessionFinishData,
    SessionListItem,
)
from app.services import practice_service, practice_session_service

router = APIRouter(prefix="/practice", tags=["陪练"])


@router.get("/meta", response_model=ApiResponse[PracticeMetaDTO], summary="陪练元数据")
def meta(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PracticeMetaDTO]:
    """抽题筛选面板与模式选择的数据来源（栈与领域 / 岗位 / 题型 / 五种模式 / 四层攻击面 / 限时档位）。"""
    return ApiResponse[PracticeMetaDTO](data=practice_service.get_meta(db))


@router.get("/mastery", response_model=ApiResponse[MasteryData], summary="领域掌握度")
def mastery(
    stack: Stack | None = Query(None, description="按技术栈过滤（枚举值）；不传 = 全部"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[MasteryData]:
    """当前账号的领域掌握度，按技术栈分组；没练过的领域不出现（前端按空态展示）。"""
    return ApiResponse[MasteryData](
        data=practice_service.list_mastery(db, user_id=current_user.id, stack=stack)
    )


@router.post("/questions", response_model=ApiResponse[QuestionListData], summary="抽题")
def pick_questions(
    payload: QuestionPickRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[QuestionListData]:
    """按筛选条件抽题（`SMART` 薄弱优先 / `RANDOM` 纯随机）；响应**不含答案与 rubric**（防先看答案）。"""
    items = practice_service.pick_questions(
        db,
        user_id=current_user.id,
        stacks=payload.stacks,
        directions=payload.directions,
        qtypes=payload.qtypes,
        mode=payload.mode.value if payload.mode else None,
        count=payload.count,
        strategy=payload.strategy,
    )
    return ApiResponse[QuestionListData](data=QuestionListData(items=items))


@router.get("/sessions", response_model=ApiResponse[PageData[SessionListItem]], summary="训练历史")
def list_sessions(
    mode: PracticeMode | None = Query(None, description="按训练模式过滤（枚举值）"),
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[SessionListItem]]:
    """当前账号的训练历史：按开始时间倒序，题干预览截断展示。"""
    data = practice_session_service.list_sessions(
        db, user_id=current_user.id, mode=mode, page=page, page_size=page_size
    )
    return ApiResponse[PageData[SessionListItem]](data=data)


@router.post(
    "/sessions", status_code=201, response_model=ApiResponse[SessionCreateData], summary="开一场训练"
)
def open_session(
    payload: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[SessionCreateData]:
    """开一场训练：**纯落库、零 LLM 调用**，第一轮内容由 `practice-turn` 产出。"""
    data = practice_session_service.open_session(
        db,
        user_id=current_user.id,
        question_id=payload.question_id,
        mode=payload.mode.value,
        time_limit=payload.time_limit,
    )
    return ApiResponse[SessionCreateData](data=data)


@router.get(
    "/sessions/{session_id}", response_model=ApiResponse[SessionDetailData], summary="单场回看"
)
def get_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[SessionDetailData]:
    """会话信息 + 逐轮记录；**参考答案仅结算后返回**（追问中给等于泄题）。"""
    return ApiResponse[SessionDetailData](
        data=practice_session_service.get_session_detail(
            db, user_id=current_user.id, session_id=session_id
        )
    )


@router.post(
    "/sessions/{session_id}/finish",
    response_model=ApiResponse[SessionFinishData],
    summary="结算本场训练",
)
def finish_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[SessionFinishData]:
    """结算：聚合各轮评分 → 判通过 → 未通过入错题本 → 重算掌握度；重复调用**幂等**。"""
    return ApiResponse[SessionFinishData](
        data=practice_session_service.finish_session(
            db, user_id=current_user.id, session_id=session_id
        )
    )
