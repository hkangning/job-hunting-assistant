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


class Stack(StrEnum):
    """题目所属技术栈（question.stack）：决定一道题服务哪些岗位。"""

    JAVA_BACKEND = "JAVA_BACKEND"  # Java 后端（Java / JVM / 并发 / Spring）
    PYTHON = "PYTHON"  # Python（基础 / 异步 / Web）
    AI_AGENT = "AI_AGENT"  # AI 与大模型应用（LLM 基础 / 提示词 / RAG / Agent）
    BACKEND_COMMON = "BACKEND_COMMON"  # 后端通用（MySQL / Redis / 消息队列）
    COMMON = "COMMON"  # 计算机通用基础（网络 / 操作系统 / 算法 / 设计模式）


class Direction(StrEnum):
    """题目/面试方向（question.direction、interview_session.direction）：知识领域。"""

    JAVA = "JAVA"  # Java 语言与集合
    JVM = "JVM"  # JVM 内存、GC、类加载、调优
    CONCURRENCY = "CONCURRENCY"  # Java 并发与多线程
    SPRING = "SPRING"  # Spring / Spring Boot / MyBatis
    MYSQL = "MYSQL"  # MySQL 与 SQL 优化
    REDIS = "REDIS"  # Redis 与缓存
    MQ = "MQ"  # 消息队列
    NETWORK = "NETWORK"  # 计算机网络
    OS = "OS"  # 操作系统
    ALGO = "ALGO"  # 数据结构与算法
    DESIGN = "DESIGN"  # 设计模式与架构
    PY_BASIC = "PY_BASIC"  # Python 语言基础
    PY_ASYNC = "PY_ASYNC"  # Python 并发与异步
    PY_WEB = "PY_WEB"  # Python Web 框架
    LLM_BASIC = "LLM_BASIC"  # 大模型基础原理
    PROMPT = "PROMPT"  # 提示词工程
    RAG = "RAG"  # 检索增强生成
    AGENT = "AGENT"  # Agent 与工具调用
    GENERAL = "GENERAL"  # 通用综合（不参与题库分类，仅供模拟面试使用）


class SessionStatus(StrEnum):
    """模拟面试会话状态（interview_session.status）。"""

    ACTIVE = "ACTIVE"  # 进行中
    FINISHED = "FINISHED"  # 已结束（已生成总结）


class ExperienceItemSource(StrEnum):
    """面经条目来源（experience_item.source_type）。"""

    LLM_EXTRACT = "LLM_EXTRACT"  # AI 提取
    MANUAL = "MANUAL"  # 手动补充


class QuestionType(StrEnum):
    """题型（question.qtype）：客观题可规则判定对错，不调 LLM；场景题按四维度评分。"""

    SUBJECTIVE = "SUBJECTIVE"  # 主观题（LLM 判定对错）
    CHOICE = "CHOICE"  # 客观题（规则判定）
    SCENARIO = "SCENARIO"  # 场景题（LLM 按四维度评分，rubric 为评分标尺）


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


class UserRole(StrEnum):
    """账号角色（user.role）：本期无权限差异，为后续管理功能预留。"""

    USER = "USER"  # 普通用户
    ADMIN = "ADMIN"  # 管理员（预留，本期不启用）


class UserPlan(StrEnum):
    """账号套餐（user.plan）：预留字段，本期不启用。"""

    FREE = "FREE"  # 免费版
    PRO = "PRO"  # 高级版（预留）
