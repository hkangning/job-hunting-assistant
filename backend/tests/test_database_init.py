"""建表冒烟（TC-51）：15 表存在、字段/索引/约束与设计文档一致、默认值正确、种子题库就位。

期望值来源：《数据库设计文档》v1.1 §3，固化在 tests/expected_schema.py。
设计依据：docs/superpowers/specs/2026-09-24-步骤2建表冒烟测试-design.md

约定：写数据的用例一律 flush + rollback，**不 commit**——保证用例之间互不残留，
否则种子题库类断言（题数、题干唯一）会被前面用例插入的临时数据干扰。
"""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

import app.models.enums as enums
from app.database import SessionLocal, engine, init_db
from app.models import (
    AgentConversation,
    Application,
    CampusEvent,
    Config,
    Experience,
    ExperienceItem,
    InterviewQa,
    InterviewSession,
    JdAnalysisReport,
    Question,
    Reminder,
    UserProfile,
    WrongQuestion,
)
from tests.expected_schema import (
    CONFIG_DEFAULTS,
    ENUM_MEMBERS,
    SEED_DIRECTIONS,
    SEED_MIN_PER_DIRECTION,
    SEED_MIN_TOTAL,
    TABLES,
)


def _columns_of(table: str) -> dict[str, tuple[str, bool, bool]]:
    """读实际库的列：{列名: (类型字符串, 允许为空, 是否主键)}。"""
    insp = inspect(engine)
    pk_columns = set(insp.get_pk_constraint(table)["constrained_columns"])
    return {
        col["name"]: (str(col["type"]), bool(col["nullable"]), col["name"] in pk_columns)
        for col in insp.get_columns(table)
    }


def test_all_15_tables_exist(client: TestClient):
    """用例 1：经应用启动（lifespan → init_db）后，15 张表全部建出。"""
    actual = set(inspect(engine).get_table_names())
    missing = set(TABLES) - actual
    assert not missing, f"缺失表：{sorted(missing)}"


def test_table_columns_match_doc(client: TestClient):
    """用例 2：逐表核对列名、类型、可空性、主键，与设计文档 §3 一致。"""
    for table, spec in TABLES.items():
        actual = _columns_of(table)
        expected = {
            name: (ctype, nullable, is_pk)
            for name, ctype, nullable, is_pk in spec["columns"]
        }
        assert set(actual) == set(expected), (
            f"{table} 列名不符：多出 {sorted(set(actual) - set(expected))}，"
            f"缺少 {sorted(set(expected) - set(actual))}"
        )
        for name, want in expected.items():
            assert actual[name] == want, f"{table}.{name} 期望 {want}，实际 {actual[name]}"


def test_table_indexes_match_doc(client: TestClient):
    """用例 3：核对显式索引名与列；SQLite 自动索引由用例 4/11 的约束断言覆盖。"""
    insp = inspect(engine)
    for table, spec in TABLES.items():
        actual = {
            idx["name"]: idx["column_names"]
            for idx in insp.get_indexes(table)
            if not idx["name"].startswith("sqlite_autoindex")
        }
        assert actual == spec["indexes"], (
            f"{table} 索引不符：期望 {spec['indexes']}，实际 {actual}"
        )


def test_unique_constraints_match_doc(client: TestClient):
    """用例 4：核对唯一约束（wrong_question / reminder / campus_event 三处）。"""
    insp = inspect(engine)
    for table, spec in TABLES.items():
        actual = sorted(
            tuple(sorted(uc["column_names"])) for uc in insp.get_unique_constraints(table)
        )
        expected = sorted(tuple(sorted(cols)) for cols in spec["uniques"])
        assert actual == expected, f"{table} 唯一约束不符：期望 {expected}，实际 {actual}"


def test_foreign_keys_match_doc(client: TestClient):
    """用例 5：核对 7 处外键的（本表列 → 目标表.目标列）。"""
    insp = inspect(engine)
    for table, spec in TABLES.items():
        actual = sorted(
            (
                fk["constrained_columns"][0],
                fk["referred_table"],
                fk["referred_columns"][0],
            )
            for fk in insp.get_foreign_keys(table)
        )
        expected = sorted(tuple(fk) for fk in spec["foreign_keys"])
        assert actual == expected, f"{table} 外键不符：期望 {expected}，实际 {actual}"


def test_sqlite_pragmas(client: TestClient):
    """用例 6：设计文档 §1 要求——WAL 模式与外键开关均开启。"""
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_foreign_key_enforced(client: TestClient):
    """用例 7：外键开关真生效——引用不存在的 application.id 应被拒绝。"""
    with SessionLocal() as db:
        db.add(
            JdAnalysisReport(
                application_id=999_999, jd_text="JD 原文", report_text="报告全文"
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_default_rows_created(client: TestClient):
    """用例 8：初始行——user_profile 仅 id=1 一条；config 含 8 个默认项且值正确。"""
    with SessionLocal() as db:
        assert [p.id for p in db.scalars(select(UserProfile)).all()] == [1]
        actual = {c.key: c.value for c in db.scalars(select(Config)).all()}
        assert actual == CONFIG_DEFAULTS, f"config 默认项不符：{actual}"


def test_enum_column_defaults(client: TestClient):
    """用例 9：枚举列默认值——插入时不指定，读回应为设计文档规定的值。"""
    with SessionLocal() as db:
        application = Application(company="甲公司", position="后端开发")
        question = Question(direction="JAVA", content="默认值验证题", answer="参考答案")
        db.add_all([application, question])
        db.flush()

        session = InterviewSession(company="甲公司", position="后端开发")
        experience = Experience(original_text="面经原文")
        conversation = AgentConversation()
        db.add_all([session, experience, conversation])
        db.flush()

        qa = InterviewQa(session_id=session.id, seq=1, question="第一题")
        item = ExperienceItem(experience_id=experience.id, question="面经问题")
        wrong = WrongQuestion(
            question_id=question.id, source_type="MANUAL", next_review_at=datetime.now()
        )
        reminder = Reminder(
            reminder_type="FOLLOW_UP", content="跟进提醒", remind_date=date.today()
        )
        db.add_all([qa, item, wrong, reminder])
        db.flush()

        for row in (application, session, question, qa, item, wrong, reminder):
            db.refresh(row)

        assert application.status == "APPLIED"
        assert session.direction == "GENERAL"
        assert session.status == "ACTIVE"
        assert question.qtype == "SUBJECTIVE"
        assert question.source == "BUILTIN"
        assert qa.is_voice == 0
        assert qa.skipped == 0
        assert item.source_type == "LLM_EXTRACT"
        assert wrong.review_stage == 1
        assert wrong.wrong_count == 0
        assert reminder.checked == 0
        db.rollback()


def test_int_and_text_defaults(client: TestClient):
    """用例 10：整型/文本默认值，以及时间戳列非空。"""
    with SessionLocal() as db:
        application = Application(company="乙公司", position="后端开发")
        question = Question(direction="OS", content="默认值验证题二", answer="答案")
        db.add_all([application, question])
        db.flush()

        session = InterviewSession(company="乙公司", position="后端开发")
        experience = Experience(original_text="面经原文二")
        conversation = AgentConversation()
        db.add_all([session, experience, conversation])
        db.flush()

        for row in (application, question, session, experience, conversation):
            db.refresh(row)

        assert session.question_count == 8
        assert experience.item_count == 0
        assert conversation.title == "新对话"
        assert application.applied_at is not None
        assert application.created_at is not None
        assert application.updated_at is not None
        assert question.created_at is not None
        assert session.created_at is not None
        assert experience.created_at is not None
        assert conversation.created_at is not None
        assert conversation.updated_at is not None
        db.rollback()


def test_unique_constraints_enforced(client: TestClient):
    """用例 11：唯一约束真生效——三处重复插入均被拒。"""
    # wrong_question.question_id 唯一
    with SessionLocal() as db:
        question = Question(direction="MYSQL", content="唯一约束验证题", answer="答案")
        db.add(question)
        db.flush()
        db.add(
            WrongQuestion(
                question_id=question.id, source_type="MANUAL", next_review_at=datetime.now()
            )
        )
        db.flush()
        db.add(
            WrongQuestion(
                question_id=question.id, source_type="PRACTICE", next_review_at=datetime.now()
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    # reminder(reminder_type, ref_id, remind_date) 唯一
    with SessionLocal() as db:
        today = date.today()
        db.add(Reminder(reminder_type="FOLLOW_UP", ref_id=1, content="提醒一", remind_date=today))
        db.flush()
        db.add(Reminder(reminder_type="FOLLOW_UP", ref_id=1, content="提醒二", remind_date=today))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    # campus_event(title, event_date) 唯一
    with SessionLocal() as db:
        event_date = datetime.now()
        db.add(CampusEvent(title="宣讲会", event_date=event_date))
        db.flush()
        db.add(CampusEvent(title="宣讲会", event_date=event_date))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_seed_questions_count(client: TestClient):
    """用例 12：种子题库总量 ≥120，Java/MySQL/网络/OS 四方向各 ≥30。"""
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(Question))
        assert total >= SEED_MIN_TOTAL, f"种子题总数 {total} < {SEED_MIN_TOTAL}"

        for direction in SEED_DIRECTIONS:
            count = db.scalar(
                select(func.count())
                .select_from(Question)
                .where(Question.direction == direction)
            )
            assert count >= SEED_MIN_PER_DIRECTION, (
                f"{direction} 方向 {count} 题 < {SEED_MIN_PER_DIRECTION}"
            )


def test_seed_questions_fields(client: TestClient):
    """用例 13：种子题字段合法——枚举取值合法、题干答案非空、题干唯一、来源均为 BUILTIN。"""
    valid_directions = ENUM_MEMBERS["Direction"]
    valid_qtypes = ENUM_MEMBERS["QuestionType"]
    valid_sources = ENUM_MEMBERS["QuestionSource"]

    with SessionLocal() as db:
        rows = db.scalars(select(Question)).all()
        assert rows, "题库为空"

        contents = [row.content for row in rows]
        assert len(contents) == len(set(contents)), "题干存在重复（种子导入去重失效）"

        for row in rows:
            assert row.direction in valid_directions, f"非法方向：{row.direction}"
            assert row.qtype in valid_qtypes, f"非法题型：{row.qtype}"
            assert row.source in valid_sources, f"非法来源：{row.source}"
            assert row.source == "BUILTIN", f"种子题来源应为 BUILTIN：{row.content[:20]}"
            assert row.content.strip(), "题干为空"
            assert row.answer.strip(), f"答案为空：{row.content[:20]}"


def test_init_db_idempotent(client: TestClient):
    """用例 14：重复初始化不产生副作用——表数、题数、画像行数均不变。"""
    tables_before = set(inspect(engine).get_table_names())
    with SessionLocal() as db:
        questions_before = db.scalar(select(func.count()).select_from(Question))
        profiles_before = db.scalar(select(func.count()).select_from(UserProfile))

    init_db()  # client fixture 已触发过一次，这里构成"重复初始化"

    assert set(inspect(engine).get_table_names()) == tables_before
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Question)) == questions_before
        assert db.scalar(select(func.count()).select_from(UserProfile)) == profiles_before


def test_enum_members_match_doc():
    """用例 15：10 个枚举类的成员取值与设计文档 §5 逐值一致（纯 Python 断言，不碰库）。"""
    for enum_name, expected in ENUM_MEMBERS.items():
        enum_cls = getattr(enums, enum_name)
        actual = {member.value for member in enum_cls}
        assert actual == expected, f"{enum_name} 与文档不符：期望 {expected}，实际 {actual}"
