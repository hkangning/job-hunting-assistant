"""数据库结构期望值：逐字段固化自《数据库设计文档》v1.5 §3，供建表冒烟测试（TC-51）比对。

本文件只存数据、不写逻辑：设计文档升版时同步改这里。
类型字符串取 SQLAlchemy 在 SQLite 下的编译结果（String(n)→VARCHAR(n)、Text→TEXT、
DateTime→DATETIME、Date→DATE、Integer→INTEGER）。

多账号改造（v1.3）后：表数 15 → **17**（新增 `user`、`llm_provider_config`），
8 张账号私有表补 `user_id` + `idx_*_user` 索引，`wrong_question` / `reminder` /
`user_profile` / `config` 四张表的约束一并变更。
"""

# 每表结构：columns 元组为 (列名, 类型, 允许为空, 是否主键)
TABLES: dict[str, dict] = {
    "application": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("company", "VARCHAR(100)", False, False),
            ("position", "VARCHAR(100)", False, False),
            ("city", "VARCHAR(50)", True, False),
            ("expected_salary", "VARCHAR(50)", True, False),
            ("applied_at", "DATETIME", False, False),
            ("channel", "VARCHAR(50)", True, False),
            ("status", "VARCHAR(20)", False, False),
            ("close_reason", "VARCHAR(20)", True, False),
            ("next_event_at", "DATETIME", True, False),
            ("remark", "TEXT", True, False),
            ("created_at", "DATETIME", False, False),
            ("updated_at", "DATETIME", False, False),
        ],
        "indexes": {
            "idx_application_user": ["user_id"],
            "idx_application_status": ["status"],
            "idx_application_applied_at": ["applied_at"],
        },
        "uniques": [],
        "foreign_keys": [("user_id", "user", "id")],
    },
    "jd_analysis_report": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("application_id", "INTEGER", True, False),
            ("jd_text", "TEXT", False, False),
            ("report_text", "TEXT", False, False),
            ("score", "INTEGER", True, False),
            ("is_finished", "INTEGER", False, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_jd_user": ["user_id"], "idx_jd_app_id": ["application_id"]},
        "uniques": [],
        "foreign_keys": [("user_id", "user", "id"), ("application_id", "application", "id")],
    },
    "interview_session": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("application_id", "INTEGER", True, False),
            ("company", "VARCHAR(100)", False, False),
            ("position", "VARCHAR(100)", False, False),
            ("direction", "VARCHAR(20)", False, False),
            ("question_count", "INTEGER", False, False),
            ("status", "VARCHAR(20)", False, False),
            ("summary", "TEXT", True, False),
            ("created_at", "DATETIME", False, False),
            ("finished_at", "DATETIME", True, False),
        ],
        "indexes": {"idx_session_user": ["user_id"], "idx_session_status": ["status"]},
        "uniques": [],
        "foreign_keys": [("user_id", "user", "id"), ("application_id", "application", "id")],
    },
    "interview_qa": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("session_id", "INTEGER", False, False),
            ("seq", "INTEGER", False, False),
            ("question", "TEXT", False, False),
            ("answer", "TEXT", True, False),
            ("is_voice", "INTEGER", False, False),
            ("score", "INTEGER", True, False),
            ("review", "TEXT", True, False),
            ("skipped", "INTEGER", False, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_qa_session": ["session_id"]},
        "uniques": [],
        "foreign_keys": [("session_id", "interview_session", "id")],
    },
    "experience": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("company", "VARCHAR(100)", True, False),
            ("position", "VARCHAR(100)", True, False),
            ("source", "VARCHAR(100)", True, False),
            ("original_text", "TEXT", False, False),
            ("item_count", "INTEGER", False, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_experience_user": ["user_id"]},
        "uniques": [],
        "foreign_keys": [("user_id", "user", "id")],
    },
    "experience_item": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("experience_id", "INTEGER", False, False),
            ("question", "TEXT", False, False),
            ("answer_points", "TEXT", True, False),
            ("source_type", "VARCHAR(20)", False, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_exp_item_exp": ["experience_id"]},
        "uniques": [],
        "foreign_keys": [("experience_id", "experience", "id")],
    },
    "question": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("stack", "VARCHAR(20)", False, False),
            ("direction", "VARCHAR(20)", False, False),
            ("content", "TEXT", False, False),
            ("answer", "TEXT", False, False),
            ("rubric", "TEXT", True, False),
            ("qtype", "VARCHAR(20)", False, False),
            ("source", "VARCHAR(20)", False, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {
            "idx_question_direction": ["direction"],
            "idx_question_stack": ["stack"],
        },
        "uniques": [],
        "foreign_keys": [],
    },
    "practice_record": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("question_id", "INTEGER", False, False),
            ("user_answer", "TEXT", False, False),
            ("score", "INTEGER", True, False),
            ("review", "TEXT", True, False),
            ("is_correct", "INTEGER", True, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {
            "idx_practice_user": ["user_id"],
            "idx_practice_q": ["question_id"],
            "idx_practice_time": ["created_at"],
        },
        "uniques": [],
        "foreign_keys": [("user_id", "user", "id"), ("question_id", "question", "id")],
    },
    "wrong_question": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("question_id", "INTEGER", False, False),
            ("source_type", "VARCHAR(20)", False, False),
            ("review_stage", "INTEGER", False, False),
            ("next_review_at", "DATETIME", False, False),
            ("wrong_count", "INTEGER", False, False),
            ("last_review_at", "DATETIME", True, False),
            ("mastered_at", "DATETIME", True, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {
            "idx_wq_user": ["user_id"],
            "idx_wq_review": ["next_review_at"],
            "idx_wq_stage": ["review_stage"],
        },
        # 多账号改造前为 UNIQUE(question_id)：现为"同账号内一题仅一条"
        "uniques": [["user_id", "question_id"]],
        "foreign_keys": [("user_id", "user", "id"), ("question_id", "question", "id")],
    },
    "agent_conversation": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("title", "VARCHAR(100)", False, False),
            ("created_at", "DATETIME", False, False),
            ("updated_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_agent_conv_user": ["user_id"]},
        "uniques": [],
        "foreign_keys": [("user_id", "user", "id")],
    },
    "agent_message": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("conversation_id", "INTEGER", False, False),
            ("role", "VARCHAR(10)", False, False),
            ("content", "TEXT", False, False),
            ("tool_name", "VARCHAR(50)", True, False),
            ("tool_args", "TEXT", True, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_agent_msg_conv": ["conversation_id"]},
        "uniques": [],
        "foreign_keys": [("conversation_id", "agent_conversation", "id")],
    },
    "reminder": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("reminder_type", "VARCHAR(20)", False, False),
            ("ref_id", "INTEGER", True, False),
            ("content", "TEXT", False, False),
            ("remind_date", "DATE", False, False),
            ("checked", "INTEGER", False, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_reminder_user": ["user_id"], "idx_reminder_date": ["remind_date"]},
        # 多账号改造前为 UNIQUE(reminder_type, ref_id, remind_date)：现为"同账号同日不重复"
        "uniques": [["user_id", "reminder_type", "ref_id", "remind_date"]],
        "foreign_keys": [("user_id", "user", "id")],
    },
    "campus_event": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("title", "VARCHAR(200)", False, False),
            ("company", "VARCHAR(100)", True, False),
            ("event_date", "DATETIME", False, False),
            ("location", "VARCHAR(200)", True, False),
            ("source_url", "VARCHAR(500)", True, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_event_date": ["event_date"]},
        "uniques": [["title", "event_date"]],
        "foreign_keys": [],
    },
    "config": {
        "columns": [
            # 联合主键：user_id = 0 为系统级（数据库设计 §3.14）
            ("user_id", "INTEGER", False, True),
            ("key", "VARCHAR(50)", False, True),
            ("value", "TEXT", True, False),
            ("updated_at", "DATETIME", False, False),
        ],
        "indexes": {},
        "uniques": [],
        "foreign_keys": [],
    },
    "user_profile": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("name", "VARCHAR(50)", True, False),
            ("school", "VARCHAR(100)", True, False),
            ("major", "VARCHAR(100)", True, False),
            ("degree", "VARCHAR(20)", True, False),
            ("gpa", "VARCHAR(20)", True, False),
            ("english_level", "VARCHAR(50)", True, False),
            ("resume_text", "TEXT", True, False),
            ("target_position", "VARCHAR(100)", True, False),
            ("target_city", "VARCHAR(50)", True, False),
            ("skills", "TEXT", True, False),
            ("weaknesses", "TEXT", True, False),
            ("note", "TEXT", True, False),
            ("updated_at", "DATETIME", False, False),
        ],
        "indexes": {},
        # 每账号有且仅有一条画像（多账号改造前靠"仅 id=1 一行"的约定）
        "uniques": [["user_id"]],
        "foreign_keys": [("user_id", "user", "id")],
    },
    "user": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("username", "VARCHAR(50)", False, False),
            ("password_hash", "VARCHAR(100)", False, False),
            ("nickname", "VARCHAR(50)", True, False),
            ("email", "VARCHAR(100)", True, False),
            ("avatar", "VARCHAR(200)", True, False),
            ("role", "VARCHAR(20)", False, False),
            ("plan", "VARCHAR(20)", False, False),
            ("login_fail_count", "INTEGER", False, False),
            ("locked_until", "DATETIME", True, False),
            ("last_login_at", "DATETIME", True, False),
            ("password_changed_at", "DATETIME", True, False),
            ("created_at", "DATETIME", False, False),
            ("updated_at", "DATETIME", False, False),
        ],
        "indexes": {},
        "uniques": [["username"]],
        "foreign_keys": [],
    },
    "llm_provider_config": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("provider", "VARCHAR(30)", False, False),
            ("base_url", "VARCHAR(200)", True, False),
            ("api_key", "TEXT", True, False),
            ("model", "VARCHAR(100)", True, False),
            ("models_cache", "TEXT", True, False),
            ("is_active", "INTEGER", False, False),
            ("created_at", "DATETIME", False, False),
            ("updated_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_llm_cfg_user": ["user_id"]},
        "uniques": [["user_id", "provider"]],
        "foreign_keys": [("user_id", "user", "id")],
    },
}

# 《数据库设计文档》§5 枚举口径（全系统唯一口径）
ENUM_MEMBERS: dict[str, set[str]] = {
    "ApplicationStatus": {"APPLIED", "WRITTEN", "INTERVIEW", "OFFER", "CLOSED"},
    "CloseReason": {"FAILED", "DECLINED", "EXPIRED"},
    # 题库升级（2026-09-26）：Direction 5 → 19（18 个领域 + GENERAL，GENERAL 不参与题库分类）
    "Direction": {
        "JAVA", "JVM", "CONCURRENCY", "SPRING",
        "MYSQL", "REDIS", "MQ",
        "ALGO", "DESIGN", "NETWORK", "OS",
        "PY_BASIC", "PY_ASYNC", "PY_WEB",
        "LLM_BASIC", "PROMPT", "RAG", "AGENT",
        "GENERAL",
    },
    # 技术栈（题目所属，决定一道题服务哪些岗位）
    "Stack": {"JAVA_BACKEND", "PYTHON", "AI_AGENT", "BACKEND_COMMON", "COMMON"},
    "SessionStatus": {"ACTIVE", "FINISHED"},
    "ExperienceItemSource": {"LLM_EXTRACT", "MANUAL"},
    "QuestionType": {"SUBJECTIVE", "CHOICE", "SCENARIO"},
    "QuestionSource": {"BUILTIN", "AI_GENERATED"},
    "WrongSourceType": {"PRACTICE", "INTERVIEW", "MANUAL"},
    "ReminderType": {"FOLLOW_UP", "WRONG_QUESTION", "INTERVIEW"},
    "MessageRole": {"USER", "ASSISTANT", "TOOL"},
    # 步骤 5 新增两个枚举（数据库设计 §5 user.role / user.plan）
    "UserRole": {"USER", "ADMIN"},
    "UserPlan": {"FREE", "PRO"},
}

# 《数据库设计文档》§4 种子题库要求（2026-09-26 题库升级：128 → 585 题）
# 两层分类 = 5 个技术栈 × 18 个领域，题型含 152 道场景题（全部带 rubric 评分标尺）
SEED_MIN_TOTAL = 585
SEED_MIN_PER_STACK = 60  # 实测最小为 AI_AGENT 70
SEED_STACKS = ("JAVA_BACKEND", "PYTHON", "AI_AGENT", "BACKEND_COMMON", "COMMON")
SEED_MIN_PER_DIRECTION = 10  # 实测最小为 15（AGENT / PROMPT / RAG）
SEED_DIRECTIONS = (
    "JAVA", "JVM", "CONCURRENCY", "SPRING",
    "MYSQL", "REDIS", "MQ",
    "ALGO", "DESIGN", "NETWORK", "OS",
    "PY_BASIC", "PY_ASYNC", "PY_WEB",
    "LLM_BASIC", "PROMPT", "RAG", "AGENT",
)

# app/database.py 的 SYSTEM_CONFIG（user_id=0，建表时插入）
# crawl_url 已废弃（SRS v1.11 / 数据库设计 v1.5：抓取目标改由信息源清单承载），后端三处已删
SYSTEM_CONFIG = {
    "crawl_enabled": "false",
}

# app/database.py 的 ACCOUNT_CONFIG（注册时按账号插入，键与接口文档 GET /settings 字段对应）
ACCOUNT_CONFIG = {
    "tts_enabled": "false",
    "voice_enabled": "false",
    "default_question_count": "8",
    "asr_provider": "funasr",
    "tts_voice": "zh-CN-XiaoxiaoNeural",
    "guide_done": "false",
}
