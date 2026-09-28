"""错题本模块传输模型（接口文档 3.9；表结构见数据库设计 3.9）。"""

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer, model_validator

from app.models.enums import Direction
from app.schemas.practice import ChoiceOption
from app.utils.datetime_utils import format_datetime


class WrongQuestionItem(BaseModel):
    """错题条目（列表项与添加响应共用）。"""

    id: int = Field(description="错题条目 id")
    question_id: int = Field(description="题目 id")
    content: str = Field(description="题干（联表 question 取全量）")
    qtype: str = Field(description="题型枚举值（选择题复习走选项点选，与陪练同口径）")
    options: list[ChoiceOption] | None = Field(
        default=None,
        description="选择题选项数组；仅 qtype=CHOICE 有值、其余为 null。不含正确标记，可安全下发",
    )
    direction: str = Field(description="知识领域，枚举 Direction")
    source_type: str = Field(description="入本来源，枚举 WrongSourceType")
    review_stage: int = Field(description="复习档位 1~4；5 = 四档已走完（对应 mastered_at 有值）")
    next_review_at: datetime = Field(description="下次复习时间（到期判定依据）")
    wrong_count: int = Field(description="累计答错次数（手动添加与知识点入本不计入）")
    mastered_at: datetime | None = Field(description="掌握时间；null = 尚未掌握")

    @field_serializer("next_review_at", "mastered_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class WrongQuestionAddRequest(BaseModel):
    """添加错题的两种形态（二选一，接口文档 §3.9）。

    题库题形态给 `question_id`；面试 / 练习知识点形态给 `content` + `answer` + `direction` + `source_type`。
    """

    question_id: int | None = Field(default=None, description="题库题形态：题目 id（须存在且本账号未入本）")
    content: str | None = Field(default=None, max_length=2000, description="知识点形态：题干（不在题库时自动建题）")
    answer: str | None = Field(default=None, max_length=5000, description="知识点形态：标准答案（自动建题与后续判定用）")
    direction: Direction | None = Field(default=None, description="知识点形态：知识领域，枚举 Direction")
    source_type: str | None = Field(
        default=None, description="知识点形态：入本来源，仅 INTERVIEW（面试点评）/ DRILL（练习模式）"
    )

    @model_validator(mode="after")
    def _check_shape(self) -> "WrongQuestionAddRequest":
        """知识点形态四个字段必须齐备；题库题形态以 `question_id` 为准、其余字段忽略。"""
        if self.question_id is not None:
            return self
        required = {
            "content": self.content,
            "answer": self.answer,
            "direction": self.direction,
            "source_type": self.source_type,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"知识点形态缺少必填字段：{' / '.join(missing)}")
        if self.source_type not in ("INTERVIEW", "DRILL"):
            raise ValueError("source_type 仅支持 INTERVIEW（面试点评）或 DRILL（练习模式）")
        return self


class WrongQuestionReviewRequest(BaseModel):
    """复习作答（提交答案后判定并按结果推进档位）。"""

    answer: str = Field(min_length=1, max_length=5000, description="本次复习的作答内容")


class WrongQuestionReviewData(BaseModel):
    """复习判定结果。"""

    correct: bool = Field(description="是否答对：客观题规则比对 / 主观题与场景题 LLM 判定")
    explain: str = Field(description="判定解析：客观题给标准答案对照，LLM 判定给点评")
    review_stage: int = Field(description="本次复习后的档位 1~5（5 = 已掌握）")
    next_review_at: datetime = Field(description="下次复习时间（答对顺延 / 答错回第 1 档）")
    mastered: bool = Field(description="是否已掌握（四档走完）")

    @field_serializer("next_review_at")
    def _serialize_datetime(self, value: datetime) -> str:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)
