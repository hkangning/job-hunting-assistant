"""演示 / 手动测试数据集（**非** pytest 用例数据）。

一套可重复导入的标准数据，覆盖当前已实现功能的各类场景，供：
- **手动测试**：导入后打开界面即见完整效果（投递看板五种状态、概览的待面试与跟进、个人中心画像、AI 配置）；
- **演示准备**：开发计划步骤 29「预置演示账号与一套数据」的落地件。

用法（在 `backend/` 目录下）：

```bash
.venv/Scripts/python.exe -m tests.demo_dataset           # 重建演示数据
.venv/Scripts/python.exe -m tests.demo_dataset --purge   # 顺带清除联调留下的临时账号
```

**幂等**：默认先删除两个演示账号及其数据再重建，可反复执行。

**`--purge`** 只按前缀（见 `_TEST_ACCOUNT_PREFIXES`）清除验证过程中产生的临时账号，
**不碰开发者自己注册的账号**——开发库的账号列表被测试残留淹没时用它清理。

**范围说明**：只覆盖**当前已实现**的功能——投递、画像、AI 配置、错题。
JD 分析 / 模拟面试 / 面经 / 练习模式的数据待各步骤落地后补充：它们的页面尚未实现，
现在插入既无处可见，表结构也可能随实现调整。

**时间一律相对「导入当天」计算**（如「明天有面试」「9 天前投递」），
故数据不会随时间失效——这正是不能写死日期的原因。
"""

import sys
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_db
from app.models import (
    Application,
    Config,
    LlmProviderConfig,
    Question,
    User,
    UserProfile,
    WrongQuestion,
)
from app.models.enums import ApplicationStatus, CloseReason, QuestionSource, WrongSourceType
from app.schemas.auth import RegisterRequest
from app.services import auth_service
from app.utils.security import encrypt_text

# ---------- 账号 ----------

DEMO_PASSWORD = "demo123456"
DEMO_USERNAME = "demo"  # 主演示账号：覆盖投递全场景
SECOND_USERNAME = "demo2"  # 隔离验证账号：换账号后应看不到主账号的任何数据

# ---------- 投递（覆盖五种状态与各类时间场景）----------
#
# 刻意造出的形态（对应可验收的行为）：
#   · 明日面试一条 → 概览「待面试」置顶并带「明天」标记
#   · 未来笔试两条 → 按时间升序排在面试之后
#   · 逾期跟进三条（9 / 5 / 4 天）→ 概览按天数降序，最久的排最前
#   · 未满 3 天一条 → 不进跟进列表
#   · 「待笔试 + 5 天前」一条 → 状态允许且未安排下一步，进跟进列表
#   · 「待笔试 + 已排未来笔试」一条 → 视为有进展，**不进**跟进列表
#   · 已结束两种原因各一条 → 卡片带对应标记
#
# `event_hour`：下次笔试/面试的钟点。刻意用白天时段而非「导入时刻 + N 天」——
# 后者会显示成 18:17 这种不像面试时间的结果。
APPLICATIONS = [
    dict(company="浩鲸科技", position="Java 后端开发", city="南京", salary="18-25K",
         channel="BOSS直聘", status=ApplicationStatus.INTERVIEW, days_ago=8,
         event_in_days=1, event_hour=14, remark="二面，面试官偏 JVM 与并发"),
    dict(company="字节跳动", position="后端开发工程师", city="北京", salary="25-35K",
         channel="内推", status=ApplicationStatus.INTERVIEW, days_ago=6,
         event_in_days=3, event_hour=15, remark="三轮技术面，注意算法"),
    dict(company="美团", position="Java 开发工程师", city="北京", salary="20-30K",
         channel="官网", status=ApplicationStatus.WRITTEN, days_ago=7,
         event_in_days=2, event_hour=19, remark="笔试 2 小时，含算法与 SQL"),
    dict(company="云启信息", position="后端开发", city="杭州", salary="15-20K",
         channel="BOSS直聘", status=ApplicationStatus.WRITTEN, days_ago=5,
         remark="笔试已做，等结果"),
    dict(company="星环数据", position="数据开发工程师", city="上海", salary="18-28K",
         channel="牛客网", status=ApplicationStatus.APPLIED, days_ago=9,
         remark="投了没回音，需要跟进"),
    dict(company="某某科技", position="前端开发", city="南京", salary="14-20K",
         channel="官网", status=ApplicationStatus.APPLIED, days_ago=4),
    dict(company="途牛旅游", position="Java 开发", city="南京", salary="12-18K",
         channel="BOSS直聘", status=ApplicationStatus.APPLIED, days_ago=1),
    dict(company="苏宁易购", position="后端开发", city="南京", salary="16-22K",
         channel="官网", status=ApplicationStatus.OFFER, days_ago=20,
         remark="已发 offer，等回复截止日"),
    dict(company="焦点科技", position="Java 开发", city="南京", salary="15-20K",
         channel="内推", status=ApplicationStatus.CLOSED, days_ago=30,
         close_reason=CloseReason.FAILED, remark="三面被拒，并发基础不扎实"),
    dict(company="汇通达", position="后端开发", city="南京", salary="14-18K",
         channel="官网", status=ApplicationStatus.CLOSED, days_ago=25,
         close_reason=CloseReason.DECLINED, remark="薪资谈不拢，主动放弃"),
]

# ---------- 求职画像 ----------

PROFILE = {
    "name": "张同学",
    "school": "南京理工大学",
    "major": "计算机科学与技术",
    "degree": "硕士",
    "gpa": "3.6/4.0",
    "english_level": "CET-6 512",
    "resume_text": (
        "硕士在读，方向为分布式系统。熟悉 Java 生态，参与过校内选课系统的后端重构"
        "（Spring Boot + MySQL + Redis）；实习期间负责过一个中等规模服务的性能优化，"
        "将慢查询占比从 12% 降到 3%。"
    ),
    "target_position": "Java 后端开发",
    "target_city": "南京",
    "skills": "Java,Spring Boot,MySQL,Redis,消息队列",
    "weaknesses": "分布式与高并发实战经验不足；算法刷题量偏少",
    "note": "希望在南京或杭州发展，接受出差",
}

# ---------- AI 配置（演示用假 Key）----------
# 仅让界面呈现「已配置 / 当前使用中」状态。要真实调用 AI，请在 AI 配置页换成自己的 Key。
LLM_PROVIDER = "deepseek"
LLM_MODEL = "deepseek-flash"
LLM_PLACEHOLDER_KEY = "sk-demo-placeholder-replace-me"

# ---------- 错题： (距今天到期天数, 是否已掌握) ----------
# 到期未复习 2 道 → 概览「错题复习」显示 2 道到期；4 道全部计入个人中心的总数
WRONG_QUESTIONS = [(2, False), (5, False), (1, True), (-3, False)]


def _now() -> datetime:
    return datetime.now()


def _delete_demo_users(db: Session) -> None:
    """删除两个演示账号及其业务数据（幂等重建的前置）。

    只删演示账号自己的行，不碰其他账号——开发库里可能有开发者自己注册的账号。
    """
    usernames = (DEMO_USERNAME, SECOND_USERNAME)
    user_ids = list(db.scalars(select(User.id).where(User.username.in_(usernames))))
    if not user_ids:
        return
    for model in (Application, WrongQuestion, LlmProviderConfig, Config, UserProfile):
        db.execute(delete(model).where(model.user_id.in_(user_ids)))
    db.execute(delete(User).where(User.id.in_(user_ids)))
    db.flush()


def _create_account(db: Session, username: str, nickname: str) -> User:
    """经服务层注册（顺带建好画像与账号级配置，与真实注册路径一致）。"""
    data = auth_service.register(
        db,
        RegisterRequest(username=username, password=DEMO_PASSWORD, nickname=nickname),
    )
    return db.get(User, data.user.id)


def _fill_profile(db: Session, user_id: int) -> None:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    for key, value in PROFILE.items():
        setattr(profile, key, value)
    profile.updated_at = _now()
    db.flush()


def _add_llm_config(db: Session, user_id: int) -> None:
    """配一家供应商并激活——AI 配置页会呈现「当前使用中」。"""
    db.add(
        LlmProviderConfig(
            user_id=user_id,
            provider=LLM_PROVIDER,
            api_key=encrypt_text(LLM_PLACEHOLDER_KEY),
            model=LLM_MODEL,
            is_active=1,
            updated_at=_now(),
        )
    )
    db.flush()


def _add_applications(db: Session, user_id: int) -> int:
    now = _now()
    for item in APPLICATIONS:
        event_in_days = item.get("event_in_days")
        event_at = None
        if event_in_days:
            # 事件钟点取数据里指定的白天时段（见 APPLICATIONS 顶部说明）
            event_at = (now + timedelta(days=event_in_days)).replace(
                hour=item.get("event_hour", 14), minute=0, second=0, microsecond=0
            )
        close_reason = item.get("close_reason")
        db.add(
            Application(
                user_id=user_id,
                company=item["company"],
                position=item["position"],
                city=item.get("city"),
                expected_salary=item.get("salary"),
                channel=item.get("channel"),
                status=item["status"].value,
                close_reason=close_reason.value if close_reason else None,
                applied_at=now - timedelta(days=item["days_ago"]),
                next_event_at=event_at,
                remark=item.get("remark"),
            )
        )
    db.flush()
    return len(APPLICATIONS)


def _add_wrong_questions(db: Session, user_id: int) -> int:
    """从题库取若干道**不同**的题入错题本（`UNIQUE(user_id, question_id)` 约束要求不重复）。"""
    question_ids = list(db.scalars(select(Question.id).order_by(Question.id).limit(len(WRONG_QUESTIONS))))
    assert len(question_ids) == len(WRONG_QUESTIONS), "题库题数不足——请先启动一次服务导入种子"
    now = _now()
    for question_id, (due_in_days, mastered) in zip(question_ids, WRONG_QUESTIONS):
        db.add(
            WrongQuestion(
                user_id=user_id,
                question_id=question_id,
                source_type=WrongSourceType.PRACTICE.value,
                next_review_at=now - timedelta(days=due_in_days),
                mastered_at=now if mastered else None,
            )
        )
    db.flush()
    return len(WRONG_QUESTIONS)


def reset_and_load(db: Session) -> dict[str, int]:
    """重建演示数据（先删后建，幂等）。返回各表写入条数。"""
    _delete_demo_users(db)

    demo = _create_account(db, DEMO_USERNAME, "演示账号")
    _fill_profile(db, demo.id)
    _add_llm_config(db, demo.id)
    applications = _add_applications(db, demo.id)
    wrong_questions = _add_wrong_questions(db, demo.id)

    # 第二个账号：只放一条投递，用于验证「换账号后看不到别人的数据」
    other = _create_account(db, SECOND_USERNAME, "隔离验证账号")
    db.add(
        Application(
            user_id=other.id,
            company="另一个账号的公司",
            position="后端开发",
            status=ApplicationStatus.APPLIED.value,
            applied_at=_now() - timedelta(days=4),
        )
    )

    db.commit()
    return {"applications": applications, "wrong_questions": wrong_questions, "profiles": len(PROFILE)}


# 验证 / 调试过程中产生的临时账号名前缀。`--purge` 时按前缀清除，**不动其他账号**
# （开发者自己的账号、演示账号都不受影响）。
_TEST_ACCOUNT_PREFIXES = ("link_", "link9", "empty_", "diag_", "lay_", "step", "tmp_", "check_")


def purge_test_accounts(db: Session) -> list[str]:
    """清除验证过程中留下的临时账号（按 `_TEST_ACCOUNT_PREFIXES` 前缀匹配）。

    这些账号是联调 / 断言脚本创建的，会淹没开发库的账号列表、干扰演示选账号。
    **只按前缀删**——不碰开发者自己注册的账号与演示账号。
    """
    victims = [
        user
        for user in db.scalars(select(User))
        if user.username.startswith(_TEST_ACCOUNT_PREFIXES)
    ]
    if not victims:
        db.commit()
        return []
    ids = [u.id for u in victims]
    for model in (Application, WrongQuestion, LlmProviderConfig, Config, UserProfile):
        db.execute(delete(model).where(model.user_id.in_(ids)))
    db.execute(delete(User).where(User.id.in_(ids)))
    db.commit()
    return [u.username for u in victims]


def main() -> None:
    purge = "--purge" in sys.argv
    init_db()  # 幂等：建表 + 系统配置 + 题库种子（题库不全会导致错题无题可用）
    with SessionLocal() as db:
        purged = purge_test_accounts(db) if purge else []
        summary = reset_and_load(db)
    print(
        "演示数据已重建：\n"
        f"  账号 {DEMO_USERNAME} / {SECOND_USERNAME}（密码 {DEMO_PASSWORD}）\n"
        f"  投递 {summary['applications']} 条（覆盖五种状态与各类时间场景）\n"
        f"  错题 {summary['wrong_questions']} 条（2 道到期 / 1 道已掌握 / 1 道未到期）\n"
        f"  画像 {summary['profiles']} 个字段 + AI 配置 1 家（假 Key，仅用于展示状态）"
    )
    if purge:
        print(f"  已清除临时账号 {len(purged)} 个：{'、'.join(purged) if purged else '（无）'}")


if __name__ == "__main__":
    main()
