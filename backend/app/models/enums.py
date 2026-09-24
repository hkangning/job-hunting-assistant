"""全部枚举类（唯一口径=数据库设计文档第 5 章）：DB 存 VARCHAR 大写英文码，DTO 层做 str/enum 转换。"""

from enum import StrEnum


class ApplicationStatus(StrEnum):
    """投递进度状态（application.status）。"""

    APPLIED = "APPLIED"  # 已投递
    WRITTEN = "WRITTEN"  # 待笔试
    INTERVIEW = "INTERVIEW"  # 面试中
    OFFER = "OFFER"  # 已获 offer
    CLOSED = "CLOSED"  # 已结束


class CloseReason(StrEnum):
    """投递结束原因（application.close_reason，仅 status=CLOSED 时有值）。"""

    FAILED = "FAILED"  # 未通过（笔试/面试被淘汰）
    DECLINED = "DECLINED"  # 主动放弃（拒 offer、不去面试等）
    EXPIRED = "EXPIRED"  # 无消息（长期无进展，自己归档）


class Direction(StrEnum):
    """题目/面试方向（question.direction、interview_session.direction）。"""

    JAVA = "JAVA"  # Java 后端
    MYSQL = "MYSQL"  # 数据库
    NETWORK = "NETWORK"  # 计算机网络
    OS = "OS"  # 操作系统
    GENERAL = "GENERAL"  # 通用综合


class SessionStatus(StrEnum):
    """模拟面试会话状态（interview_session.status）。"""

    ACTIVE = "ACTIVE"  # 进行中
    FINISHED = "FINISHED"  # 已结束（已生成总结）


class ExperienceItemSource(StrEnum):
    """面经条目来源（experience_item.source_type）。"""

    LLM_EXTRACT = "LLM_EXTRACT"  # AI 提取
    MANUAL = "MANUAL"  # 手动补充


class QuestionType(StrEnum):
    """题型（question.qtype）：客观题可规则判定对错，不调 LLM。"""

    SUBJECTIVE = "SUBJECTIVE"  # 主观题（LLM 判定）
    CHOICE = "CHOICE"  # 客观题（规则判定）


class QuestionSource(StrEnum):
    """题目来源（question.source）。"""

    BUILTIN = "BUILTIN"  # 内置种子
    AI_GENERATED = "AI_GENERATED"  # AI 生成入库


class WrongSourceType(StrEnum):
    """错题入本来源（wrong_question.source_type）。"""

    PRACTICE = "PRACTICE"  # 陪练答错入本
    INTERVIEW = "INTERVIEW"  # 面试知识点入本
    MANUAL = "MANUAL"  # 手动添加


class ReminderType(StrEnum):
    """提醒类型（reminder.reminder_type）。"""

    FOLLOW_UP = "FOLLOW_UP"  # 投递跟进（3 天无进展）
    WRONG_QUESTION = "WRONG_QUESTION"  # 错题到期
    INTERVIEW = "INTERVIEW"  # 待面试提醒


class MessageRole(StrEnum):
    """Agent 消息角色（agent_message.role）。"""

    USER = "USER"  # 用户
    ASSISTANT = "ASSISTANT"  # AI 回复（可含工具调用）
    TOOL = "TOOL"  # 工具执行结果
