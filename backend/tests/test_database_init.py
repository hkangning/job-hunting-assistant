"""建表冒烟（TC-51）：17 表存在、字段/索引/约束与设计文档一致、默认值正确、注册预置数据、种子题库就位。

期望值来源：《数据库设计文档》v1.5 §3~§4，固化在 tests/expected_schema.py。
设计依据：docs/superpowers/specs/2026-09-24-步骤2建表冒烟测试-design.md

约定：写数据的用例一律 flush + rollback，**不 commit**——保证用例之间互不残留，
否则种子题库类断言（题数、题干唯一）会被前面用例插入的临时数据干扰。
需要真实提交的用例（注册预置数据）改走 HTTP 接口，由接口自身提交。

步骤 5（多账号）后：账号私有写入一律带 `user_id`，故需要账号的用例加 `account` fixture。
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
    User,
    UserProfile,
    WrongQuestion,
)
from tests.expected_schema import (
    ACCOUNT_CONFIG,
    ENUM_MEMBERS,
    SEED_DIRECTIONS,
    SEED_MIN_PER_DIRECTION,
    SEED_MIN_TOTAL,
    SYSTEM_CONFIG,
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


def _new_user(db, username: str = "helper_user") -> User:
    """造一个账号行（用例内部使用，password_hash 占位即可）。

    默认名不能用 "tester"——`client` fixture 已注册该账号，重名会撞 `user.username` 唯一约束。
    """
    user = User(username=username, password_hash="x")
    db.add(user)
    db.flush()
    return user


def test_all_17_tables_exist(client: TestClient):
    """用例 1：经应用启动（lifespan → init_db）后，17 张表全部建出（多账号改造前为 15 张）。"""
    actual = set(inspect(engine).get_table_names())
    missing = set(TABLES) - actual
    assert not missing, f"缺失表：{sorted(missing)}"
    assert len(TABLES) == 17, f"期望 17 张表，期望值文件中有 {len(TABLES)} 张"


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
    """用例 4：核对唯一约束（user / user_profile / wrong_question / reminder / campus_event / llm_provider_config）。"""
    insp = inspect(engine)
    for table, spec in TABLES.items():
        actual = sorted(
            tuple(sorted(uc["column_names"])) for uc in insp.get_unique_constraints(table)
        )
        expected = sorted(tuple(sorted(cols)) for cols in spec["uniques"])
        assert actual == expected, f"{table} 唯一约束不符：期望 {expected}，实际 {actual}"


def test_foreign_keys_match_doc(client: TestClient):
    """用例 5：核对外键（本表列 → 目标表.目标列），含 8 张私有表指向 user 的归属外键。"""
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
        user = _new_user(db)
        db.add(
            JdAnalysisReport(
                user_id=user.id, application_id=999_999, jd_text="JD 原文", report_text="报告全文"
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_default_rows_created(client: TestClient, account):
    """用例 8：初始行——系统级 config（user_id=0）2 条；画像与账号级配置**随注册产生**，建表时不预置。

    多账号改造前建表会预置一条 `id=1` 的空画像（单用户假设），现改为每账号在注册时建。
    """
    with SessionLocal() as db:
        rows = db.scalars(select(Config)).all()
        assert {row.key: row.value for row in rows if row.user_id == 0} == SYSTEM_CONFIG
        assert {row.user_id for row in rows} == {0, account["id"]}, "config 应只有系统级与默认账号两组"

        # 画像条数与账号一一对应（client 注册了 1 个账号 → 恰 1 条），而非建表时预置
        profiles = db.scalars(select(UserProfile)).all()
        assert [p.user_id for p in profiles] == [account["id"]]


def test_register_provisions_account_data(client: TestClient, account):
    """用例 8b：注册为新账号预置**一条空画像 + 6 项账号级 config**（数据库设计 §4）。"""
    with SessionLocal() as db:
        user_id = account["id"]
        profiles = db.scalars(select(UserProfile).where(UserProfile.user_id == user_id)).all()
        assert len(profiles) == 1, "每个账号应有且仅有一条画像"
        assert profiles[0].name is None

        account_config = {
            row.key: row.value
            for row in db.scalars(select(Config).where(Config.user_id == user_id)).all()
        }
        assert account_config == ACCOUNT_CONFIG

        # 系统级配置不因注册而变动
        system_rows = db.scalars(select(Config).where(Config.user_id == 0)).all()
        assert {row.key for row in system_rows} == set(SYSTEM_CONFIG)


def test_enum_column_defaults(client: TestClient, account):
    """用例 9：枚举列默认值——插入时不指定，读回应为设计文档规定的值。"""
    with SessionLocal() as db:
        user_id = account["id"]
        application = Application(user_id=user_id, company="甲公司", position="后端开发")
        question = Question(direction="JAVA", content="默认值验证题", answer="参考答案")
        db.add_all([application, question])
        db.flush()

        session = InterviewSession(user_id=user_id, company="甲公司", position="后端开发")
        experience = Experience(user_id=user_id, original_text="面经原文")
        conversation = AgentConversation(user_id=user_id)
        db.add_all([session, experience, conversation])
        db.flush()

        qa = InterviewQa(session_id=session.id, seq=1, question="第一题")
        item = ExperienceItem(experience_id=experience.id, question="面经问题")
        wrong = WrongQuestion(
            user_id=user_id, question_id=question.id, source_type="MANUAL",
            next_review_at=datetime.now(),
        )
        reminder = Reminder(
            user_id=user_id, reminder_type="FOLLOW_UP", content="跟进提醒", remind_date=date.today()
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


def test_int_and_text_defaults(client: TestClient, account):
    """用例 10：整型/文本默认值、时间戳列非空，以及账号表的枚举与计数默认值。"""
    with SessionLocal() as db:
        user_id = account["id"]
        application = Application(user_id=user_id, company="乙公司", position="后端开发")
        question = Question(direction="OS", content="默认值验证题二", answer="答案")
        db.add_all([application, question])
        db.flush()

        session = InterviewSession(user_id=user_id, company="乙公司", position="后端开发")
        experience = Experience(user_id=user_id, original_text="面经原文二")
        conversation = AgentConversation(user_id=user_id)
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

        # 账号表：role / plan / 失败计数默认值（数据库设计 §3.16）
        new_user = _new_user(db, username="default_checker")
        db.refresh(new_user)
        assert new_user.role == "USER"
        assert new_user.plan == "FREE"
        assert new_user.login_fail_count == 0
        assert new_user.locked_until is None
        assert new_user.password_changed_at is None
        db.rollback()


def test_unique_constraints_enforced(client: TestClient, account, make_account):
    """用例 11：唯一约束真生效，且**账号隔离口径正确**——同账号重复被拒、跨账号互不冲突。"""
    other = make_account("other_user")

    # wrong_question：UNIQUE(user_id, question_id)——跨账号各存一份成功，同账号重复被拒
    with SessionLocal() as db:
        question = Question(direction="MYSQL", content="唯一约束验证题", answer="答案")
        db.add(question)
        db.flush()

        db.add(WrongQuestion(
            user_id=account["id"], question_id=question.id, source_type="MANUAL",
            next_review_at=datetime.now(),
        ))
        db.add(WrongQuestion(
            user_id=other["id"], question_id=question.id, source_type="MANUAL",
            next_review_at=datetime.now(),
        ))
        db.flush()  # 两个账号各一条，应成功（多账号改造前 UNIQUE(question_id) 会拒）
        assert db.scalar(select(func.count()).select_from(WrongQuestion)) == 2

        db.add(WrongQuestion(
            user_id=account["id"], question_id=question.id, source_type="PRACTICE",
            next_review_at=datetime.now(),
        ))
        with pytest.raises(IntegrityError):
            db.flush()  # 同账号同题第二条：被拒
        db.rollback()

    # reminder：UNIQUE(user_id, reminder_type, ref_id, remind_date)——同账号同日不重复
    with SessionLocal() as db:
        today = date.today()
        db.add(Reminder(
            user_id=account["id"], reminder_type="FOLLOW_UP", ref_id=1, content="提醒一", remind_date=today
        ))
        db.flush()
        db.add(Reminder(
            user_id=account["id"], reminder_type="FOLLOW_UP", ref_id=1, content="提醒二", remind_date=today
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    # campus_event(title, event_date) 唯一：公共表，与账号无关
    with SessionLocal() as db:
        event_date = datetime.now()
        db.add(CampusEvent(title="宣讲会", event_date=event_date))
        db.flush()
        db.add(CampusEvent(title="宣讲会", event_date=event_date))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    # user.username 唯一（库层只管精确重复；大小写变体由服务层拦，见 TC-52）
    with SessionLocal() as db:
        db.add(User(username="dup_user", password_hash="x"))
        db.flush()
        db.add(User(username="dup_user", password_hash="x"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    # user_profile：UNIQUE(user_id)——每账号仅一条（client 已为其账号建过一条）
    with SessionLocal() as db:
        db.add(UserProfile(user_id=account["id"], updated_at=datetime.now()))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_seed_questions_count(client: TestClient):
    """用例 12：种子题库总量 ≥120，Java/MySQL/网络/OS 四方向各 ≥30（题库为公共表，全账号共享）。"""
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
    """用例 14：重复初始化不产生副作用——表数、题数、config 行数均不变。"""
    tables_before = set(inspect(engine).get_table_names())
    with SessionLocal() as db:
        questions_before = db.scalar(select(func.count()).select_from(Question))
        configs_before = db.scalar(select(func.count()).select_from(Config))

    init_db()  # client fixture 已触发过一次，这里构成"重复初始化"

    assert set(inspect(engine).get_table_names()) == tables_before
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Question)) == questions_before
        assert db.scalar(select(func.count()).select_from(Config)) == configs_before


def test_enum_members_match_doc():
    """用例 15：12 个枚举类的成员取值与设计文档 §5 逐值一致（纯 Python 断言，不碰库）。"""
    for enum_name, expected in ENUM_MEMBERS.items():
        enum_cls = getattr(enums, enum_name)
        actual = {member.value for member in enum_cls}
        assert actual == expected, f"{enum_name} 与文档不符：期望 {expected}，实际 {actual}"
