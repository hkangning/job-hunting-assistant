"""数据库结构期望值：逐字段固化自《数据库设计文档》v1.15 §3，供建表冒烟测试（TC-51）比对。

本文件只存数据、不写逻辑：设计文档升版时同步改这里。
类型字符串取 SQLAlchemy 在 SQLite 下的编译结果（String(n)→VARCHAR(n)、Text→TEXT、
DateTime→DATETIME、Date→DATE、Integer→INTEGER）。

多账号改造（v1.3）后：表数 15 → **17**（新增 `user`、`llm_provider_config`），
8 张账号私有表补 `user_id` + `idx_*_user` 索引，`wrong_question` / `reminder` /
`user_profile` / `config` 四张表的约束一并变更。

八股陪练升级为「训练系统」（数据库设计 v1.14）后：表数 17 → **19**（新增
`practice_session`、`domain_mastery`），`practice_record` 扩 4 列
（`session_id` / `round_index` / `round_kind` / `elapsed_ms`）、`user_answer`
放宽为可空、并新增 `idx_practice_session` 与指向 `practice_session` 的外键。
**注意**：该表走的是手工 `ALTER`（`create_all` 不给已存在的表补列，见数据库设计 §7.3），
开发库与测试库都要执行一次，否则逐轮点评与历史查询会报「未知列」。

选择题选项与解析（数据库设计 v1.15）后：`question` 新增 `options` / `explanation`
两列（均 TEXT 可空，**仅 `qtype=CHOICE` 有值**——非选择题不得带这两个字段），
同样走手工 `ALTER`（§7.3），开发库与测试库都要执行一次，否则启动导入即报
「Unknown column 'question.options'」；`WrongSourceType` 补 `DRILL`
（文档 v1.7 先行定义、本次代码落地，练习模式知识点入本）。

面试阶段化 + 三条功能需求（数据库设计 v1.18 / v1.19）后，本轮共 6 处列变更：
`interview_session` 加 `stage_plan` / `intensity`、`interview_qa` 加 `stage`、
`application` 加 `jd_text`、`user_profile` 加 `experiences` 并删 `resume_text`
（有损删除，画像改结构化经历）。均走手工 `ALTER`（§7.3 有完整 SQL），
开发库与测试库都要执行一次。

校招情报采集层（数据库设计 v1.21）后：表数 19 → **20**（新增 `crawl_source`），
`campus_event` 扩 9 列、删 `created_at`（7 → 15 列），唯一约束
`UNIQUE(title, event_date)` → **`UNIQUE(dedup_key)`**（跨源去重指纹），
并新增 `idx_event_status`。`campus_event` 走手工 `ALTER`、`crawl_source`
随 `create_all` 自动建（§7.3 有完整 SQL），开发库与测试库都要执行一次。

校招情报岗位与订阅（数据库设计 v1.23 / v1.24）后：表数 20 → **22**（新增
`job_posting` 与 `subscription`）。`job_posting` 为混合归属表——`user_id=0`
自动抓取（公共）/ 账号 id 投喂（私有），故 **`user_id` 不建外键**；`subscription.user_id`
建外键指向 `user.id`（账号私有）。两表随 `create_all` 自动建（§7.3 有等价 SQL），
开发库与测试库都要执行一次。
"""

# 每表结构：columns 元组为 (列名, 类型, 允许为空, 是否主键)
TABLES: dict[str, dict] = {
    "application": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("company", "VARCHAR(100)", False, False),
            ("position", "VARCHAR(100)", False, False),
            ("jd_text", "TEXT", True, False),
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
            ("stage_plan", "TEXT", True, False),
            ("intensity", "VARCHAR(20)", True, False),
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
            ("stage", "VARCHAR(20)", False, False),
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
            ("options", "TEXT", True, False),
            ("explanation", "TEXT", True, False),
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
            ("session_id", "INTEGER", True, False),
            ("round_index", "INTEGER", False, False),
            ("round_kind", "VARCHAR(20)", False, False),
            ("elapsed_ms", "INTEGER", True, False),
            ("user_answer", "TEXT", True, False),
            ("score", "INTEGER", True, False),
            ("review", "TEXT", True, False),
            ("is_correct", "INTEGER", True, False),
            ("next_choices", "TEXT", True, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {
            "idx_practice_user": ["user_id"],
            "idx_practice_q": ["question_id"],
            "idx_practice_time": ["created_at"],
            "idx_practice_session": ["session_id"],
        },
        "uniques": [],
        "foreign_keys": [
            ("user_id", "user", "id"),
            ("question_id", "question", "id"),
            ("session_id", "practice_session", "id"),
        ],
    },
    "practice_session": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("question_id", "INTEGER", False, False),
            ("mode", "VARCHAR(20)", False, False),
            ("status", "VARCHAR(20)", False, False),
            ("time_limit", "INTEGER", True, False),
            ("overall_score", "INTEGER", True, False),
            ("break_face", "VARCHAR(20)", True, False),
            ("hint_count", "INTEGER", False, False),
            ("passed", "INTEGER", True, False),
            ("wrong_question_id", "INTEGER", True, False),
            ("started_at", "DATETIME", False, False),
            ("finished_at", "DATETIME", True, False),
        ],
        "indexes": {
            "idx_ps_user": ["user_id"],
            "idx_ps_question": ["question_id"],
            "idx_ps_time": ["started_at"],
        },
        "uniques": [],
        "foreign_keys": [
            ("user_id", "user", "id"),
            ("question_id", "question", "id"),
            ("wrong_question_id", "wrong_question", "id"),
        ],
    },
    "domain_mastery": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("stack", "VARCHAR(20)", False, False),
            ("direction", "VARCHAR(20)", False, False),
            ("mastery", "INTEGER", False, False),
            ("answered_count", "INTEGER", False, False),
            ("covered_count", "INTEGER", False, False),
            ("last_practiced_at", "DATETIME", True, False),
        ],
        "indexes": {
            "idx_dm_user": ["user_id"],
        },
        "uniques": [
            ["user_id", "stack", "direction"],
        ],
        "foreign_keys": [("user_id", "user", "id")],
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
            ("ref_type", "VARCHAR(20)", True, False),
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
            ("info_type", "VARCHAR(20)", False, False),
            ("major_req", "VARCHAR(300)", True, False),
            ("source_site", "VARCHAR(50)", True, False),
            ("dedup_key", "VARCHAR(64)", False, False),
            ("content_hash", "VARCHAR(64)", True, False),
            ("status", "VARCHAR(20)", False, False),
            ("first_seen_at", "DATETIME", False, False),
            ("last_seen_at", "DATETIME", False, False),
            ("changed_at", "DATETIME", True, False),
        ],
        "indexes": {"idx_event_date": ["event_date"], "idx_event_status": ["status", "event_date"]},
        # 多源采集改造前为 UNIQUE(title, event_date)：现按跨源去重指纹 dedup_key 唯一
        "uniques": [["dedup_key"]],
        "foreign_keys": [],
    },
    "job_posting": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("title", "VARCHAR(200)", False, False),
            ("company", "VARCHAR(100)", False, False),
            ("city", "VARCHAR(50)", True, False),
            ("edu_req", "VARCHAR(50)", True, False),
            ("major_req", "VARCHAR(300)", True, False),
            ("salary_text", "VARCHAR(100)", True, False),
            ("job_type", "VARCHAR(20)", True, False),
            ("deadline", "DATETIME", True, False),
            ("source_site", "VARCHAR(50)", True, False),
            ("source_url", "VARCHAR(500)", True, False),
            ("ingest_source", "VARCHAR(20)", False, False),
            ("raw_excerpt", "TEXT", True, False),
            ("dedup_key", "VARCHAR(64)", False, False),
            ("content_hash", "VARCHAR(64)", True, False),
            ("status", "VARCHAR(20)", False, False),
            ("first_seen_at", "DATETIME", False, False),
            ("last_seen_at", "DATETIME", False, False),
            ("changed_at", "DATETIME", True, False),
        ],
        "indexes": {
            "idx_job_user": ["user_id"],
            "idx_job_status": ["status", "deadline"],
            "idx_job_city": ["city"],
        },
        # 同归属内去重：公共岗位（user_id=0）与各账号投喂各按自己的指纹唯一
        "uniques": [["user_id", "dedup_key"]],
        # user_id 不建外键——取值 0（公共）非有效账号（数据库设计 §3.21）
        "foreign_keys": [],
    },
    "subscription": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("user_id", "INTEGER", False, False),
            ("name", "VARCHAR(50)", False, False),
            ("keywords", "TEXT", True, False),
            ("companies", "TEXT", True, False),
            ("cities", "TEXT", True, False),
            ("info_types", "TEXT", True, False),
            ("enabled", "INTEGER", False, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_subscription_user": ["user_id"]},
        "uniques": [],
        "foreign_keys": [("user_id", "user", "id")],
    },
    "crawl_source": {
        "columns": [
            ("id", "INTEGER", False, True),
            ("school_name", "VARCHAR(100)", False, False),
            ("system_type", "VARCHAR(20)", False, False),
            ("domain", "VARCHAR(200)", False, False),
            ("params", "TEXT", True, False),
            ("enabled", "INTEGER", False, False),
            ("last_crawl_at", "DATETIME", True, False),
            ("last_status", "VARCHAR(20)", True, False),
            ("last_error", "VARCHAR(300)", True, False),
            ("created_at", "DATETIME", False, False),
        ],
        "indexes": {"idx_crawl_source_enabled": ["enabled"]},
        "uniques": [["system_type", "domain"]],
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
            ("experiences", "TEXT", True, False),
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
    "WrongSourceType": {"PRACTICE", "DRILL", "INTERVIEW", "MANUAL"},
    "ReminderType": {"FOLLOW_UP", "WRONG_QUESTION", "INTERVIEW", "INFO_MATCH"},
    "MessageRole": {"USER", "ASSISTANT", "TOOL"},
    # 步骤 5 新增两个枚举（数据库设计 §5 user.role / user.plan）
    "UserRole": {"USER", "ADMIN"},
    "UserPlan": {"FREE", "PRO"},
}

# 《数据库设计文档》§4 种子题库要求（2026-09-28 题库升级：585 → 672 题，新增 87 道选择题）
# 两层分类 = 5 个技术栈 × 18 个领域，题型含 152 道场景题（全部带 rubric 评分标尺）
# 与 100 道选择题（全部带选项数组与解析）
SEED_MIN_TOTAL = 672
SEED_MIN_PER_STACK = 60  # 实测最小为 AI_AGENT 87
SEED_STACKS = ("JAVA_BACKEND", "PYTHON", "AI_AGENT", "BACKEND_COMMON", "COMMON")
SEED_MIN_PER_DIRECTION = 10  # 实测最小为 19（AGENT / PROMPT / RAG）
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
