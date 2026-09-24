"""数据库结构期望值：逐字段固化自《数据库设计文档》v1.1 §3，供建表冒烟测试（TC-51）比对。

本文件只存数据、不写逻辑：设计文档升版时同步改这里。
类型字符串取 SQLAlchemy 在 SQLite 下的编译结果（String(n)→VARCHAR(n)、Text→TEXT、
DateTime→DATETIME、Date→DATE、Integer→INTEGER）。
"""

# 每表结构：columns 元组为 (列名, 类型, 允许为空, 是否主键)
TABLES: dict[str, dict] = {
    "application": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("company", "VARCHAR(100)", False, False),
            ("position", "VARCHAR(100)", False, False),
            ("city", "VARCHAR(50)", True, False),
            ("expected_salary", "VARCHAR(50)", True, False),
            ("applied_at", "DATETIME", False, False),
            ("channel", "VARCHAR(50)", True, False),
            ("status", "VARCHAR(20)", False, False),
            ("next_event_at", "DATETIME", True, False),
            ("remark", "TEXT", True, False),
            ("created_at", "DATETIME", False, False),
            ("updated_at", "DATETIME", False, False),
        ],
        "indexes": {
            "idx_application_status": ["status"],
            "idx_application_applied_at": ["applied_at"],
        },
        "uniques": [],
        "foreign_keys": [],
    },
    "jd_analysis_report": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("application_id", "INTEGER", True, False),
            ("jd_text", "TEXT", False, False),
            ("report_text", "TEXT", False, False),
            ("score", "INTEGER", True, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_jd_app_id": ["application_id"]},
        "uniques": [],
        "foreign_keys": [("application_id", "application", "id")],
    },
    "interview_session": {
        "columns": [
            ("id", "INTEGER", False, True),
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
        "indexes": {"idx_session_status": ["status"]},
        "uniques": [],
        "foreign_keys": [("application_id", "application", "id")],
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
            ("company", "VARCHAR(100)", True, False),
            ("position", "VARCHAR(100)", True, False),
            ("source", "VARCHAR(100)", True, False),
            ("original_text", "TEXT", False, False),
            ("item_count", "INTEGER", False, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {},
        "uniques": [],
        "foreign_keys": [],
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
            ("direction", "VARCHAR(20)", False, False),
            ("content", "TEXT", False, False),
            ("answer", "TEXT", False, False),
            ("qtype", "VARCHAR(20)", False, False),
            ("source", "VARCHAR(20)", False, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_question_direction": ["direction"]},
        "uniques": [],
        "foreign_keys": [],
    },
    "practice_record": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("question_id", "INTEGER", False, False),
            ("user_answer", "TEXT", False, False),
            ("score", "INTEGER", True, False),
            ("review", "TEXT", True, False),
            ("is_correct", "INTEGER", True, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {
            "idx_practice_q": ["question_id"],
            "idx_practice_time": ["created_at"],
        },
        "uniques": [],
        "foreign_keys": [("question_id", "question", "id")],
    },
    "wrong_question": {
        "columns": [
            ("id", "INTEGER", False, True),
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
            "idx_wq_review": ["next_review_at"],
            "idx_wq_stage": ["review_stage"],
        },
        "uniques": [["question_id"]],
        "foreign_keys": [("question_id", "question", "id")],
    },
    "agent_conversation": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("title", "VARCHAR(100)", False, False),
            ("created_at", "DATETIME", False, False),
            ("updated_at", "DATETIME", False, False),
        ],
        "indexes": {},
        "uniques": [],
        "foreign_keys": [],
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
            ("reminder_type", "VARCHAR(20)", False, False),
            ("ref_id", "INTEGER", True, False),
            ("content", "TEXT", False, False),
            ("remind_date", "DATE", False, False),
            ("checked", "INTEGER", False, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_reminder_date": ["remind_date"]},
        "uniques": [["reminder_type", "ref_id", "remind_date"]],
        "foreign_keys": [],
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
        "uniques": [],
        "foreign_keys": [],
    },
}

# 《数据库设计文档》§5 枚举口径（全系统唯一口径）
ENUM_MEMBERS: dict[str, set[str]] = {
    "ApplicationStatus": {"APPLIED", "WRITTEN", "INTERVIEW", "OFFER", "CLOSED"},
    "Direction": {"JAVA", "MYSQL", "NETWORK", "OS", "GENERAL"},
    "SessionStatus": {"ACTIVE", "FINISHED"},
    "ExperienceItemSource": {"LLM_EXTRACT", "MANUAL"},
    "QuestionType": {"SUBJECTIVE", "CHOICE"},
    "QuestionSource": {"BUILTIN", "AI_GENERATED"},
    "WrongSourceType": {"PRACTICE", "INTERVIEW", "MANUAL"},
    "ReminderType": {"FOLLOW_UP", "WRONG_QUESTION", "INTERVIEW"},
    "MessageRole": {"USER", "ASSISTANT", "TOOL"},
}

# 《数据库设计文档》§4 种子题库要求 + 开发计划步骤 2 验收标准
SEED_MIN_TOTAL = 120
SEED_MIN_PER_DIRECTION = 30
SEED_DIRECTIONS = ("JAVA", "MYSQL", "NETWORK", "OS")

# app/database.py 的 DEFAULT_CONFIG（键与接口文档 GET /settings 响应字段一一对应）
CONFIG_DEFAULTS = {
    "llm_provider": "deepseek",
    "llm_model": "deepseek-flash",
    "llm_base_url": "",
    "tts_enabled": "false",
    "voice_enabled": "false",
    "crawl_enabled": "false",
    "crawl_url": "",
    "default_question_count": "8",
}
