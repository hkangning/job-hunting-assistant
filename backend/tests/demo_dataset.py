"""演示 / 手动测试数据集（**非** pytest 用例数据）。

一套可重复导入的标准数据，覆盖**当前已实现功能的各类场景**，供：
- **手动测试**：导入后打开界面即见完整效果（投递看板五种状态、概览的待面试与跟进、错题各档位、
  JD 报告、面试已结束与进行中、面经、陪练会话与掌握度、Agent 会话、个人中心画像、AI 配置）；
- **演示准备**：开发计划步骤 29「预置演示账号与一套数据」的落地件。

用法（在 `backend/` 目录下）：

```bash
.venv/Scripts/python.exe -m tests.demo_dataset                    # 重建演示数据（demo / demo2）
.venv/Scripts/python.exe -m tests.demo_dataset --user lsjtest     # 重建指定账号的业务数据（保留其 AI 配置）
.venv/Scripts/python.exe -m tests.demo_dataset --purge            # 重建并顺带清除联调留下的临时账号
```

**幂等**：默认先删除两个演示账号及其数据再重建，可反复执行；`--user` 对已存在账号
删除其业务数据后重建（**保留该账号的 AI 供应商配置**——用户可能配了真实 Key），
账号本身与密码不动。

**`--purge`** 只按前缀（见 `_TEST_ACCOUNT_PREFIXES`）清除验证过程中产生的临时账号，
**不碰开发者自己注册的账号**——开发库的账号列表被测试残留淹没时用它清理。

**范围**：覆盖当前已实现的功能——投递、画像、AI 配置、错题、JD 分析、模拟面试、面经、陪练、
全局 Agent（步骤 18/19）与校招情报（信息源配置 + 宣讲会 / 双选会，步骤 21 公共数据；
公共岗位 + 订阅规则，步骤 22）。

**时间一律相对「导入当天」计算**（如「明天有面试」「9 天前投递」），
故数据不会随时间失效——这正是不能写死日期的原因。
"""

import json
import sys
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clients.crawler import processor
from app.clients.crawler.base import RawItem
from app.database import SYSTEM_USER_ID, SessionLocal, init_db
from app.models import (
    AgentConversation,
    AgentMessage,
    Application,
    CampusEvent,
    Config,
    CrawlSource,
    DomainMastery,
    Experience,
    ExperienceItem,
    InterviewQa,
    InterviewSession,
    JdAnalysisReport,
    JobPosting,
    LlmProviderConfig,
    PracticeRecord,
    PracticeSession,
    Question,
    Reminder,
    Subscription,
    User,
    UserProfile,
    WrongQuestion,
)
from app.models.enums import (
    ApplicationStatus,
    CloseReason,
    CrawlStatus,
    CrawlSystemType,
    Direction,
    ExperienceItemSource,
    InfoStatus,
    InfoType,
    InterviewIntensity,
    InterviewStage,
    IngestSource,
    JobType,
    MessageRole,
    PracticeMode,
    PracticeSessionStatus,
    QuestionSource,
    QuestionType,
    RoundKind,
    SessionStatus,
    Stack,
    WrongSourceType,
)
from app.schemas.auth import RegisterRequest
from app.services import agent_service, auth_service
from app.utils.security import encrypt_text

# ---------- 账号 ----------

DEMO_PASSWORD = "demo123456"
DEMO_USERNAME = "demo"  # 主演示账号：覆盖全功能场景
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
#   · 每条带 `jd_text`（新增/编辑必填；JD 分析「条件必填」与面试出题的背景来源）
#
# `event_hour`：下次笔试/面试的钟点。刻意用白天时段而非「导入时刻 + N 天」——
# 后者会显示成 18:17 这种不像面试时间的结果。
APPLICATIONS = [
    dict(company="浩鲸科技", position="Java 后端开发", city="南京", salary="18-25K",
         channel="BOSS直聘", status=ApplicationStatus.INTERVIEW, days_ago=8,
         event_in_days=1, event_hour=14, remark="二面，面试官偏 JVM 与并发",
         jd_text="岗位职责：\n1. 负责运营商 BSS 领域后端服务的设计与开发（Java / Spring Boot）；\n"
                 "2. 参与高并发场景改造与系统性能优化；\n3. 参与技术方案评审与代码 Review。\n"
                 "任职要求：\n1. 熟悉 JVM 内存模型与 GC 调优，理解 Java 并发编程；\n"
                 "2. 熟悉 MySQL 索引与 SQL 优化，了解 Redis 常见用法与缓存问题；\n"
                 "3. 本科及以上学历，有分布式系统经验者优先。"),
    dict(company="字节跳动", position="后端开发工程师", city="北京", salary="25-35K",
         channel="内推", status=ApplicationStatus.INTERVIEW, days_ago=6,
         event_in_days=3, event_hour=15, remark="三轮技术面，注意算法",
         jd_text="岗位职责：\n1. 负责核心业务系统的后端研发（Go / Java 均可）；\n"
                 "2. 设计高可用、高并发的分布式服务；\n3. 参与系统架构演进与容量规划。\n"
                 "任职要求：\n1. 扎实的计算机基础：数据结构、算法、操作系统、网络；\n"
                 "2. 熟悉分布式系统原理（一致性、容错、负载均衡）；\n"
                 "3. 有大规模在线服务经验者优先。"),
    dict(company="美团", position="Java 开发工程师", city="北京", salary="20-30K",
         channel="官网", status=ApplicationStatus.WRITTEN, days_ago=7,
         event_in_days=2, event_hour=19, remark="笔试 2 小时，含算法与 SQL",
         jd_text="岗位职责：\n1. 负责到店业务后端服务开发（Java）；\n2. 参与营销、交易等核心链路建设；\n"
                 "3. 参与系统稳定性治理。\n任职要求：\n1. 熟悉 Java 与常用中间件（MySQL / Redis / MQ）；\n"
                 "2. 理解并发编程与 JVM 基本原理；\n3. 有交易或营销系统经验者优先。"),
    dict(company="云启信息", position="后端开发", city="杭州", salary="15-20K",
         channel="BOSS直聘", status=ApplicationStatus.WRITTEN, days_ago=5,
         remark="笔试已做，等结果",
         jd_text="岗位职责：\n1. 负责 SaaS 产品后端模块开发；\n2. 编写技术文档与单元测试。\n"
                 "任职要求：\n1. 熟悉 Java / Spring Boot / MySQL；\n2. 了解 Docker 与 CI 流程。"),
    dict(company="星环数据", position="数据开发工程师", city="上海", salary="18-28K",
         channel="牛客网", status=ApplicationStatus.APPLIED, days_ago=9,
         remark="投了没回音，需要跟进",
         jd_text="岗位职责：\n1. 负责数据平台 ETL 链路开发；\n2. 参与实时计算任务开发（Flink / Spark）。\n"
                 "任职要求：\n1. 熟悉 SQL 与至少一种大数据框架；\n2. 熟悉 Java 或 Scala。"),
    dict(company="某某科技", position="前端开发", city="南京", salary="14-20K",
         channel="官网", status=ApplicationStatus.APPLIED, days_ago=4,
         jd_text="岗位职责：\n1. 负责公司管理后台前端开发（Vue3）；\n2. 参与组件库建设。\n"
                 "任职要求：\n1. 熟悉 Vue 全家桶与工程化工具；\n2. 了解前端性能优化。"),
    dict(company="途牛旅游", position="Java 开发", city="南京", salary="12-18K",
         channel="BOSS直聘", status=ApplicationStatus.APPLIED, days_ago=1,
         jd_text="岗位职责：\n1. 负责旅游订单系统的后端开发；\n2. 参与订单履约链路优化。\n"
                 "任职要求：\n1. 熟悉 Java 基础与 Spring 生态；\n2. 熟悉 MySQL 常用调优手段。"),
    dict(company="苏宁易购", position="后端开发", city="南京", salary="16-22K",
         channel="官网", status=ApplicationStatus.OFFER, days_ago=20,
         remark="已发 offer，等回复截止日",
         jd_text="岗位职责：\n1. 负责零售中台的后端研发；\n2. 参与库存、价格等核心域建设。\n"
                 "任职要求：\n1. 熟悉 Java / Spring Cloud；\n2. 有电商或零售系统经验者优先。"),
    dict(company="焦点科技", position="Java 开发", city="南京", salary="15-20K",
         channel="内推", status=ApplicationStatus.CLOSED, days_ago=30,
         close_reason=CloseReason.FAILED, remark="三面被拒，并发基础不扎实",
         jd_text="岗位职责：\n1. 负责 B2B 平台后端开发；\n2. 参与搜索与推荐链路建设。\n"
                 "任职要求：\n1. 熟悉 Java 与常用中间件；\n2. 有高并发系统经验者优先。"),
    dict(company="汇通达", position="后端开发", city="南京", salary="14-18K",
         channel="官网", status=ApplicationStatus.CLOSED, days_ago=25,
         close_reason=CloseReason.DECLINED, remark="薪资谈不拢，主动放弃",
         jd_text="岗位职责：\n1. 负责县域零售系统后端开发；\n2. 参与系统重构。\n"
                 "任职要求：\n1. 熟悉 Java / Spring Boot / MySQL；\n2. 接受阶段性出差。"),
]

# ---------- 求职画像 ----------

PROFILE = {
    "name": "张同学",
    "school": "南京理工大学",
    "major": "计算机科学与技术",
    "degree": "硕士",
    "gpa": "3.6/4.0",
    "english_level": "CET-6 512",
    "target_position": "Java 后端开发",
    "target_city": "南京",
    "skills": "Java,Spring Boot,MySQL,Redis,消息队列",
    "weaknesses": "分布式与高并发实战经验不足；算法刷题量偏少",
    "note": "希望在南京或杭州发展，接受出差",
}

# 结构化经历条目（画像页「经历」区；JD 分析与面试「项目深挖」的输入）
PROFILE_EXPERIENCES = [
    {
        "type": "INTERNSHIP",
        "title": "后端开发实习",
        "org": "杭州云杉网络",
        "role": "后端开发实习生",
        "period": "2025.07 - 2025.10",
        "description": "参与订单服务性能优化：定位慢查询并重建索引，慢查询占比从 12% 降到 3%；"
                       "参与结算链路改造，引入本地缓存与消息队列削峰。",
    },
    {
        "type": "PROJECT",
        "title": "校内选课系统重构",
        "org": "南京理工大学",
        "role": "后端负责人",
        "period": "2024.09 - 2025.01",
        "description": "主导选课系统后端从单体到分层的重构（Spring Boot + MySQL + Redis）；"
                       "用 Redis 预热热点课程容量、Lua 脚本保证扣减原子性，抢课高峰接口 P99 从 1.2s 降到 260ms。",
    },
]

# ---------- AI 配置（演示用假 Key）----------
# 仅让界面呈现「已配置 / 当前使用中」状态。要真实调用 AI，请在 AI 配置页换成自己的 Key。
LLM_PROVIDER = "deepseek"
LLM_MODEL = "deepseek-flash"
LLM_PLACEHOLDER_KEY = "sk-demo-placeholder-replace-me"

# ---------- JD 分析报告（完整 / 关联投递 / 半成品三种形态）----------
#
# 报告全文按生成时的五段标题书写（section 规则见 prompts.JD_ANALYSIS_SECTION_RULES）：
#   ## 1. 综合匹配度评分 / ## 2. 分项评分 / ## 3. 优势清单 / ## 4. 差距清单 / ## 5. 投递与准备建议
JD_REPORTS = [
    dict(  # 关联「浩鲸科技」投递的完整报告
        application_company="浩鲸科技", score=72, is_finished=1, days_ago=7,
        jd_text="（浩鲸科技 Java 后端 JD 快照——见投递记录的 jd_text）",
        report_text=(
            "## 1. 综合匹配度评分\n"
            "综合匹配度：72 分\n"
            "技术栈与岗位要求基本对齐（Java / MySQL / Redis），JVM 与并发有实习期实战佐证；"
            "主要差距在分布式与高并发场景的深度经验。\n"
            "\n## 2. 分项评分\n"
            "- 技能匹配：78 分——Java 生态与常用中间件覆盖良好，缓存与消息队列有具体落地。\n"
            "- 经验匹配：68 分——实习期的性能优化成果有量化，但缺少分布式系统的完整项目。\n"
            "- 学历与硬性门槛：85 分——硕士在读、专业对口，满足本科及以上要求。\n"
            "\n## 3. 优势清单\n"
            "- 有可量化的性能优化经历（慢查询 12% → 3%），面试中可展开讲定位过程；\n"
            "- 选课系统重构中用到 Redis + Lua 保证原子性，缓存与并发结合说得清；\n"
            "- 技能栈与 JD 关键词重合度高（Spring Boot / MySQL / Redis / 消息队列）。\n"
            "\n## 4. 差距清单\n"
            "- JD 提到「分布式系统经验优先」——画像中无分布式项目，建议补齐一个分库分表或注册中心的实践；\n"
            "- GC 调优停留在理论层面——建议结合实习项目做一次真实调优并记录数据；\n"
            "- 运营商 BSS 领域背景为零——准备时了解一下行业特点即可，不必深挖。\n"
            "\n## 5. 投递与准备建议\n"
            "- 简历把「慢查询 12% → 3%」提到第一条成果，替换泛泛的自我评价；\n"
            "- 面试重点准备：JVM 内存与 GC、并发工具类、缓存三大问题与分布式锁；\n"
            "- 项目深挖按「背景 → 定位 → 方案对比 → 结果与代价」组织，避免只讲结果。"
        ),
    ),
    dict(  # 独立的完整报告（未关联投递）
        application_company=None, score=65, is_finished=1, days_ago=3,
        jd_text="岗位职责：\n1. 负责推荐系统后端服务开发；\n2. 参与特征工程与在线服务建设。\n"
                "任职要求：\n1. 熟悉 Java / Python 至少一门；\n2. 了解常见推荐算法与工程链路。",
        report_text=(
            "## 1. 综合匹配度评分\n"
            "综合匹配度：65 分\n"
            "后端工程能力满足基本要求，但推荐领域经验为空，需要补齐算法侧知识面。\n"
            "\n## 2. 分项评分\n"
            "- 技能匹配：70 分——Java 后端能力扎实，Python 未在画像中体现。\n"
            "- 经验匹配：55 分——无推荐系统相关项目经历。\n"
            "- 学历与硬性门槛：80 分——硕士学历满足要求。\n"
            "\n## 3. 优势清单\n"
            "- 后端工程经验完整，能支撑在线服务开发；\n"
            "- 有性能优化与缓存实践，与推荐在线服务场景部分相关。\n"
            "\n## 4. 差距清单\n"
            "- 无推荐算法基础（协同过滤 / 向量召回等），建议先补一门入门课；\n"
            "- 画像未体现大数据组件经验（Spark / Flink），JD 隐含要求特征工程链路；\n"
            "- 无 Python 项目佐证。\n"
            "\n## 5. 投递与准备建议\n"
            "- 若真心想转推荐方向，先做一个端到端的小型推荐 Demo 再投；\n"
            "- 否则建议优先投递纯后端岗位，把匹配度 72 分的那条路线走深。"
        ),
    ),
    dict(  # 半成品（断连落库；列表与详情应显示「未完成」标记）
        application_company=None, score=None, is_finished=0, days_ago=1,
        jd_text="岗位职责：\n1. 负责支付核心链路后端开发；\n2. 参与资损防控与对账系统建设。\n"
                "任职要求：\n1. 熟悉 Java 与分布式事务；\n2. 有支付或金融系统经验者优先。",
        report_text=(
            "## 1. 综合匹配度评分\n"
            "综合匹配度：70 分\n"
            "（本次分析在生成途中被中断，仅保留已完成段落）"
        ),
    ),
]

# ---------- 模拟面试（已结束带总结 / 进行中 / 存量无阶段化 三种形态）----------
#
# 每场 qa 元组：(seq, stage, question, answer, score, review, skipped)
#   · answer 为 None 且 skipped=0 → 进行中的「已提问未作答」（进行页可继续作答）
#   · skipped=1 → 跳过轮（无作答与评分）
INTERVIEWS = [
    dict(  # 已结束 + 总结 + 阶段化（大厂强度），关联「字节跳动」投递
        company="字节跳动", application_company="字节跳动",
        direction=Direction.JAVA, question_count=4, intensity=InterviewIntensity.LARGE,
        days_ago=5, finished=True,
        stages=[(InterviewStage.INTRO, 1), (InterviewStage.TECH, 2), (InterviewStage.PROJECT, 1)],
        qas=[
            (1, InterviewStage.INTRO, "请先做个两分钟的自我介绍，重点讲和这个岗位相关的经历。",
             "硕士在读，方向分布式系统。实习期间做过订单服务的性能优化，把慢查询占比从 12% 降到 3%；"
             "校内主导过选课系统重构，用 Redis + Lua 支撑抢课高峰。想找 Java 后端方向的工作。",
             7, "- 亮点：有量化成果，与岗位相关度高。\n- 不足：自我介绍偏项目罗列，缺少一条主线。\n"
                "- 建议：用「一横一纵」组织——横向技术栈、纵向最有代表性的一个项目。", 0),
            (2, InterviewStage.TECH, "说说 JVM 的运行时内存区域，以及你对 GC 分代收集的理解。",
             "线程私有的是程序计数器、虚拟机栈、本地方法栈；共享的是堆和方法区。"
             "堆分新生代和老年代，新生代 Eden + 两个 Survivor。新建对象先在 Eden，"
             "Minor GC 后存活对象进 Survivor，年龄够了晋升老年代。GC 算法有标记-清除、"
             "复制、标记-整理，分代收集里新生代用复制、老年代用标记-整理。",
             8, "- 亮点：结构完整，分代与算法的对应关系讲清楚了。\n- 不足：没有展开 CMS 与 G1 的取舍，"
                "也没提到 TLAB 与分配担保。\n- 建议：按「原理 → 参数 → 线上问题排查」三层准备。", 0),
            (3, InterviewStage.TECH, "并发场景下你怎么保证线程安全？说说你用过的工具类。",
             "主要是锁和原子类。synchronized 和 ReentrantLock，前者 JVM 层实现、有锁升级，"
             "后者是 AQS 实现、可中断可超时。原子类用 CAS。容器用 ConcurrentHashMap，"
             "线程池用 ThreadPoolExecutor。",
             6, "- 亮点：工具覆盖全面，知道锁升级与 AQS 的差异。\n- 不足：没有结合具体业务场景，"
                "追问「什么时候用哪种」会露怯。\n- 建议：每个工具配一个自己做过的场景。", 0),
            (4, InterviewStage.PROJECT, "挑一个你最有代表性的项目，讲讲你解决的难点。",
             "讲选课系统：抢课高峰数据库被打满，我把课程余量和热点课程缓存到 Redis，"
             "扣减用 Lua 脚本保证原子性，再把请求异步化，P99 从 1.2 秒降到 260 毫秒。",
             7, "- 亮点：背景 → 方案 → 结果讲得完整，有量化。\n- 不足：方案对比没讲——"
                "为什么不用消息队列削峰、CAS 扣减的 ABA 问题怎么处理。\n- 建议：补「为什么不选另一条路」的思考。", 0),
        ],
        summary=(
            "## 总体表现\n"
            "基础扎实、项目有量化的候选者。技术问答结构完整，项目讲得有条理；"
            "主要短板在「深度追问」——对取舍与边界问题的准备不足。\n"
            "\n## 亮点\n"
            "- JVM 分代与 GC 算法对应关系清晰，属于真正理解过的讲法；\n"
            "- 项目成果有数字支撑，性能优化链路完整。\n"
            "\n## 不足\n"
            "- 多个回答停在「是什么」，没到「为什么这么设计、什么时候失效」；\n"
            "- 并发题缺少业务场景绑定。\n"
            "\n## 下一步建议\n"
            "- 每个知识点按「原理 → 取舍 → 线上问题」三层补齐；\n"
            "- 项目准备「为什么不用另一种方案」的对比叙事；\n"
            "- 针对大厂强度，重点补分布式与系统设计。"
        ),
    ),
    dict(  # 进行中：最后一条「已提问未作答」，进行页可继续
        company="浩鲸科技", application_company="浩鲸科技",
        direction=Direction.JAVA, question_count=6, intensity=InterviewIntensity.MEDIUM,
        days_ago=1, finished=False,
        stages=[(InterviewStage.INTRO, 1), (InterviewStage.TECH, 5)],
        qas=[
            (1, InterviewStage.INTRO, "先简单介绍一下自己，以及为什么想投这个岗位。",
             "两年后端方向的学习与实践，主要做 Java 服务开发。看中这个岗位是因为业务场景"
             "和我的实习经历比较接近，都是交易类系统的性能与稳定性问题。",
             7, "- 亮点：动机回答真诚，与岗位关联自然。\n- 不足：可以再压缩一半时长。\n"
                "- 建议：动机部分准备 30 秒版本。", 0),
            (2, InterviewStage.TECH, "那你解释一下 Java 里 synchronized 的锁升级过程。",
             None, None, None, 0),
        ],
        summary=None,
    ),
    dict(  # 存量会话形态：无强度（按 MEDIUM 兜底显示）、无阶段计划
        company="某某网络", application_company=None,
        direction=Direction.GENERAL, question_count=3, intensity=None,
        days_ago=12, finished=True,
        stages=None,
        qas=[
            (1, InterviewStage.TECH, "介绍一个你最近在学的技术，以及你从中学到了什么。",
             "最近在系统梳理 MySQL 的索引与事务。把 B+ 树的结构、聚簇索引回表这些"
             "从「背结论」变成了能用执行计划去验证，做实验看 type 和 rows 的变化。",
             6, "- 亮点：有动手验证的习惯。\n- 不足：没有提学到了什么结论。\n"
                "- 建议：补一个「实验前后对比」的收尾。", 0),
            (2, InterviewStage.TECH, "平时怎么保持技术学习的节奏？",
             None, None, None, 1),
            (3, InterviewStage.TECH, "反问环节：你想了解我们团队什么？",
             "想了解团队的技术栈和一些正在做的挑战，也想知道新人上手一般会先接哪类任务。",
             7, "- 亮点：问题具体、指向成长路径。\n- 不足：可以再问一个关于业务方向的问题。\n"
                "- 建议：准备两个反问，一个技术一个业务。", 0),
        ],
        summary="## 总体表现\n存量会话样本（用于验证老数据的渲染与强度兜底）。\n\n## 亮点\n- 学习习惯好。\n\n"
                "## 不足\n- 回答偏概括。\n\n## 下一步建议\n- 用具体例子支撑结论。",
    ),
]

# ---------- 面经（含条目的完整形态 / 未填公司的形态）----------

EXPERIENCES = [
    dict(
        company="浩鲸科技", position="Java 后端开发", source="牛客", days_ago=6,
        original_text=(
            "浩鲸科技后端一面记录。面试官先让做自我介绍，然后直接问 JVM 内存结构，"
            "我按线程私有和共享两块答的，重点讲了堆的分代。接着问 GC 算法，"
            "分代收集里新生代复制、老年代标记-整理，还追问了 CMS 和 G1 的区别。"
            "然后转到 MySQL，问为什么索引用 B+ 树，我答了非叶节点不存数据、扇出大树高低，"
            "以及叶子链表对范围查询的友好。追问了聚簇索引和回表的区别。"
            "Redis 部分问了缓存穿透和分布式锁，穿透我答布隆过滤器加空值缓存，"
            "分布式锁讲 SETNX 加过期时间和 Lua 释放。最后手写单例，写了双重检查锁定。"
        ),
        items=[
            ("JVM 运行时内存区域有哪些？", "程序计数器、虚拟机栈、本地方法栈（线程私有）；堆、方法区（线程共享）。重点：堆的分代结构与对象分配流程。"),
            ("GC 算法有哪些？分代收集里怎么组合？", "标记-清除 / 标记-复制 / 标记-整理；新生代复制、老年代标记-整理；延伸 CMS 与 G1 的区别。"),
            ("MySQL 索引为什么选 B+ 树？", "非叶节点只存键不存数据 → 扇出大、树高低、磁盘 IO 少；叶子链表支持范围查询。哈希索引不支持范围查询。"),
            ("聚簇索引和二级索引的区别？什么是回表？", "聚簇索引叶子存整行；二级索引叶子存主键，按主键再查一次聚簇索引即回表。"),
            ("Redis 缓存穿透怎么处理？", "布隆过滤器前置拦截 + 不存在键缓存空值并设短过期；区分穿透 / 击穿 / 雪崩。"),
            ("分布式锁怎么实现？", "SETNX + 过期时间 + 唯一 value；释放用 Lua 保证原子性；可延伸 Redlock 争议。"),
            ("手写线程安全的单例模式。", "双重检查锁定（volatile + synchronized）；备选静态内部类实现。"),
        ],
    ),
    dict(  # 未填公司：验证「未填公司」的渲染与检索结果里的兜底文案
        company=None, position=None, source="同学分享", days_ago=2,
        original_text=(
            "朋友发来的一段面经：问了三道题——TCP 三次握手为什么不是两次、"
            "进程和线程的区别、手写快排。第一题我答了防止历史连接和资源浪费；"
            "第二题从资源分配和调度单位两个角度说；快排写的是单边循环版本。"
        ),
        items=[
            ("TCP 为什么需要三次握手？", "两次无法确认客户端的接收能力，且历史失效连接会浪费服务端资源；第三次让服务端确认客户端收到 SYN+ACK。"),
            ("进程和线程的区别？", "进程是资源分配的基本单位，线程是调度的基本单位；线程共享进程地址空间，切换开销更小。"),
            ("手写快速排序。", "单边循环或双边循环分区均可；注意基准选择与递归终止条件，说明平均 O(n log n) / 最坏 O(n²)。"),
        ],
    ),
]

# ---------- 陪练（已完成带结算 / 追问链进行中）与领域掌握度 ----------

PRACTICE_SESSIONS = [
    dict(  # 快练：一次作答即结算
        direction=Direction.JVM, mode=PracticeMode.QUICK, days_ago=4, finished=True,
        overall_score=7, passed=1, break_face=None, hint_count=0,
        records=[
            (1, RoundKind.OPENING, "JVM 的内存区域怎么划分？",
             "按线程私有和共享分：私有的有程序计数器、虚拟机栈、本地方法栈；"
             "共享的是堆和方法区。堆分新生代老年代，方法区 JDK8 后是元空间。",
             7, "- 亮点：分类清晰，补充了 JDK8 元空间的版本差异。\n- 不足：没提直接内存。\n"
                "- 建议：把直接内存和栈溢出场景一起准备。"),
        ],
    ),
    dict(  # 面试官深挖：追问链停在第一层（进行中）
        direction=Direction.MYSQL, mode=PracticeMode.INTERVIEWER, days_ago=1, finished=False,
        overall_score=None, passed=None, break_face=None, hint_count=0,
        records=[
            (1, RoundKind.OPENING, "MySQL 索引为什么用 B+ 树？",
             "非叶节点不存数据，同样大小的页能放更多键，树高更低，磁盘 IO 更少；"
             "叶子节点用链表相连，范围查询效率高。",
             8, "- 亮点：从磁盘 IO 和范围查询两个角度答全了。\n- 不足：没对比 B 树的具体差异。\n"
                "- 建议：用「同样 16KB 页能放多少键」做量化对比。"),
            (2, RoundKind.FOLLOW_UP, "为什么 B 树不行？B 树非叶节点也存数据，具体差在哪里？",
             "B 树的非叶节点还要存数据行，一页放不下几个键，扇出小、树就高，"
             "查一次多几次 IO；而且 B 树叶子之间没有链表，范围查询要中序遍历回跳。",
             7, "- 亮点：扇出和范围查询两点都答到了。\n- 不足：没有落到具体数字。\n"
                "- 建议：记住「16KB 页 / 主键 8 字节 → 单页千级键」这个数量级。"),
        ],
    ),
]

# 领域掌握度：(stack, direction, mastery, answered_count, covered_count)
DOMAIN_MASTERY = [
    (Stack.JAVA_BACKEND, Direction.JVM, 75, 12, 6),
    (Stack.JAVA_BACKEND, Direction.CONCURRENCY, 40, 5, 3),
    (Stack.BACKEND_COMMON, Direction.MYSQL, 62, 9, 5),
    (Stack.COMMON, Direction.NETWORK, 88, 15, 7),
]

# ---------- 错题：覆盖复习档位 / 到期状态 / 来源类型 / 选择题形态 ----------
#
# 形态说明：
#   · 到期未复习 2 道 → 概览「错题复习」显示 2 道到期；另有 1 道今日到期、1 道未到期
#   · 已掌握 1 道 → 不进到期集合；错题本里显示已掌握标记
#   · 来源覆盖 PRACTICE（题库题）/ INTERVIEW（面试知识点，新建 AI 题）/ MANUAL（手动添加）
#   · 含 1 道选择题（规则判定口径，列表带选项与题型）
WRONG_QUESTIONS = [
    dict(due_in_days=2, mastered=False, source=WrongSourceType.PRACTICE, question="pick"),
    dict(due_in_days=5, mastered=False, source=WrongSourceType.PRACTICE, question="pick"),
    dict(due_in_days=1, mastered=True, source=WrongSourceType.PRACTICE, question="pick"),
    dict(due_in_days=-3, mastered=False, source=WrongSourceType.PRACTICE, question="pick"),
    dict(due_in_days=0, mastered=False, source=WrongSourceType.INTERVIEW, question="new"),
    dict(due_in_days=3, mastered=False, source=WrongSourceType.MANUAL, question="choice"),
]

# 面试知识点入本的题干（"new" 形态：新建 AI_GENERATED 题）
INTERVIEW_WRONG_QUESTION = dict(
    content="面试追问：为什么用 volatile 就能保证双重检查锁定的单例是安全的？",
    answer="volatile 禁止指令重排：防止「分配内存 → 赋值引用 → 初始化」被重排为「赋值引用在前」，"
           "导致其他线程拿到未初始化完成的对象；同时保证可见性。",
    stack=Stack.JAVA_BACKEND, direction=Direction.CONCURRENCY,
)

# ---------- 全局 Agent 会话（查询工具执行 / 写操作确认卡 / 多轮纯文本 三种形态）----------
#
# 消息形态与真实链路落库一致（见 agent_service.run_agent_chat）：
#   · 查询类：USER → TOOL（工具结果 JSON，带 tool_name）→ ASSISTANT（总结，带 tool_name）
#   · 写操作：USER → ASSISTANT（引导文本 + tool_args JSON）——确认卡点「确认」后的执行
#     走独立端点、不写回会话，故会话停在这一步
#   · 纯文本：USER → ASSISTANT（tool_name 为 null）
#
# 消息元组：(role, 距会话开始的分钟数, content, tool_name, tool_args)；
# content 可为 callable（`(db, user_id) -> str`，装载时生成）。
# 会话 A 的 TOOL 结果不写死——经真实工具 handler 按导入后的库内数据生成（与概览页口径一致），
# 其总结文本里的数字与该数据集口径对齐（改动数据集时同步）。
# 会话列表按 updated_at 倒序（「今天」的排最前）；`title` 按真实规则取首条用户输入
# 前 30 字——改首条消息时记得同步。


def _today_summary_tool_result(db: Session, user_id: int) -> str:
    """查询类会话的 TOOL 结果文本：走真实工具 handler，按 `json.dumps` 落库口径序列化。

    handler 读的是当次导入后的库内数据，日期字段也相对导入当天——结果卡与概览页自洽。
    """
    data = agent_service.TOOLS["get_today_summary"].handler(db, user_id, {})
    return json.dumps(data, ensure_ascii=False)


AGENT_CONVERSATIONS = [
    dict(  # 查询类工具真实执行：三种形态里信息最全（会话列表最新一条）
        title="今天有什么要跟进的？",
        ago=timedelta(hours=3),
        messages=[
            (MessageRole.USER, 0, "今天有什么要跟进的？", None, None),
            (MessageRole.TOOL, 1, _today_summary_tool_result, "get_today_summary", None),
            (MessageRole.ASSISTANT, 2,
             "帮你把今天的待办过了一遍：\n\n"
             "**要盯的笔试 / 面试**\n"
             "- 浩鲸科技 · Java 后端开发：明天 14:00 面试，按面试官偏好重点过 JVM 与并发；\n"
             "- 美团 · Java 开发工程师：后天 19:00 笔试，算法与 SQL 先热身；\n"
             "- 字节跳动 · 后端开发工程师：3 天后下午面试，注意算法。\n\n"
             "**需要跟进的投递**\n"
             "- 星环数据投了 9 天没动静，今天补一条跟进；\n"
             "- 云启信息（5 天）、某某科技（4 天）也超过 3 天没更新了。\n\n"
             "**错题复习**\n"
             "- 有到期未复习的错题，抽 10 分钟过一下。",
             "get_today_summary", None),
        ],
    ),
    dict(  # 写操作确认卡：出卡后停住（点「确认」的执行不写回会话）
        title="帮我记一条投递：携程，Java 后端开发，上海",
        ago=timedelta(days=1),
        messages=[
            (MessageRole.USER, 0, "帮我记一条投递：携程，Java 后端开发，上海", None, None),
            (MessageRole.ASSISTANT, 1,
             "好的，我整理成了这条投递记录，确认没问题就点「确认入库」；有出入直接改～",
             "create_application",
             '{"company": "携程", "position": "Java 后端开发", "city": "上海"}'),
        ],
    ),
    dict(  # 纯文本多轮：无工具调用（最简形态）
        title="分布式的问题我没什么实战经验，面试怎么答稳妥？",
        ago=timedelta(days=5),
        messages=[
            (MessageRole.USER, 0, "分布式的问题我没什么实战经验，面试怎么答稳妥？", None, None),
            (MessageRole.ASSISTANT, 2,
             "没做过分布式系统不代表这道题没法答，关键是划清边界、把话题拉回能撑住的地方：\n\n"
             "1. 先坦诚边界——一句话带过「没有生产级分布式系统的完整实践」，不装懂；\n"
             "2. 接上手里的牌——选课系统重构里有 Redis 缓存、Lua 原子扣减，"
             "这些本来就是分布式场景的基础件，讲清用它们解决过什么问题；\n"
             "3. 原理层按「是什么 → 为什么 → 失效边界」答，比如一致性哈希、CAP 取舍，"
             "把理解的取舍逻辑说清楚，比背诵结论可信。\n\n"
             "面试官更在意你「知道自己不知道什么」，而不是硬凑场景。",
             None, None),
            (MessageRole.USER, 6, "那项目经历部分怎么讲比较好？", None, None),
            (MessageRole.ASSISTANT, 8,
             "按「背景 → 我的动作 → 结果 → 取舍」四段组织，重点是后两段：\n\n"
             "- **结果**要有数字：慢查询占比 12% → 3%、P99 1.2s → 260ms，这类量化最有说服力；\n"
             "- **取舍**是拉开差距的地方：为什么用 Lua 而不是分布式锁、为什么先上缓存而不是直接加索引，"
             "把「为什么不用另一条路」想明白；\n"
             "- 每个项目准备一个「如果重做会怎么改」的收尾，这是深度追问的预埋答案。",
             None, None),
        ],
    ),
]


def _now() -> datetime:
    return datetime.now()


# ---------- 清场 ----------


def _delete_account_data(db: Session, user_ids: list[int], *, keep_llm: bool = False) -> None:
    """删除账号的业务数据（幂等重建的前置；子表先删）。

    `keep_llm=True` 保留 AI 供应商配置——`--user` 对开发者自己的账号重建时用
    （账号里可能配了真实 Key），演示账号仍走全删。
    """
    if not user_ids:
        return
    # 三张子表没有 user_id，经父记录关联，先删
    db.execute(
        delete(ExperienceItem).where(
            ExperienceItem.experience_id.in_(
                select(Experience.id).where(Experience.user_id.in_(user_ids))
            )
        )
    )
    db.execute(
        delete(InterviewQa).where(
            InterviewQa.session_id.in_(
                select(InterviewSession.id).where(InterviewSession.user_id.in_(user_ids))
            )
        )
    )
    db.execute(
        delete(AgentMessage).where(
            AgentMessage.conversation_id.in_(
                select(AgentConversation.id).where(AgentConversation.user_id.in_(user_ids))
            )
        )
    )
    for model in (
        PracticeRecord,
        PracticeSession,
        WrongQuestion,
        Reminder,
        JdAnalysisReport,
        InterviewSession,
        Application,
        Experience,
        DomainMastery,
        AgentConversation,
        Subscription,
        JobPosting,
        Config,
        UserProfile,
    ):
        db.execute(delete(model).where(model.user_id.in_(user_ids)))
    if not keep_llm:
        db.execute(delete(LlmProviderConfig).where(LlmProviderConfig.user_id.in_(user_ids)))
    db.flush()


def _delete_demo_users(db: Session) -> None:
    """删除两个演示账号及其业务数据。只删演示账号自己的行，不碰其他账号。"""
    usernames = (DEMO_USERNAME, SECOND_USERNAME)
    user_ids = list(db.scalars(select(User.id).where(User.username.in_(usernames))))
    if not user_ids:
        return
    _delete_account_data(db, user_ids)
    db.execute(delete(User).where(User.id.in_(user_ids)))
    db.flush()


# ---------- 装载 ----------


def _create_account(db: Session, username: str, nickname: str) -> User:
    """经服务层注册（顺带建好画像与账号级配置，与真实注册路径一致）。"""
    data = auth_service.register(
        db,
        RegisterRequest(username=username, password=DEMO_PASSWORD, nickname=nickname),
    )
    return db.get(User, data.user.id)


def _fill_profile(db: Session, user_id: int) -> None:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if profile is None:
        # 历史账号可能没有画像行（「注册时预置画像」之前注册的）——补建
        profile = UserProfile(user_id=user_id)
        db.add(profile)
    for key, value in PROFILE.items():
        setattr(profile, key, value)
    profile.experiences = json.dumps(PROFILE_EXPERIENCES, ensure_ascii=False)
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
                jd_text=item.get("jd_text"),
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


def _add_jd_reports(db: Session, user_id: int) -> int:
    """JD 报告：complete / 独立 / 半成品三种形态（半成品列表带「未完成」标记）。"""
    now = _now()
    for item in JD_REPORTS:
        application_id = None
        company = item.get("application_company")
        if company:
            application_id = db.scalar(
                select(Application.id).where(
                    Application.user_id == user_id, Application.company == company
                )
            )
        db.add(
            JdAnalysisReport(
                user_id=user_id,
                application_id=application_id,
                jd_text=item["jd_text"],
                report_text=item["report_text"],
                score=item["score"],
                is_finished=item["is_finished"],
                created_at=now - timedelta(days=item["days_ago"]),
            )
        )
    db.flush()
    return len(JD_REPORTS)


def _add_interviews(db: Session, user_id: int) -> int:
    now = _now()
    for item in INTERVIEWS:
        application_id = None
        if item.get("application_company"):
            application_id = db.scalar(
                select(Application.id).where(
                    Application.user_id == user_id,
                    Application.company == item["application_company"],
                )
            )
        created_at = now - timedelta(days=item["days_ago"])
        session = InterviewSession(
            user_id=user_id,
            application_id=application_id,
            company=item["company"],
            position="Java 后端开发",
            direction=item["direction"].value,
            question_count=item["question_count"],
            intensity=item["intensity"].value if item["intensity"] else None,
            stage_plan=json.dumps(
                [{"stage": s.value, "count": c} for s, c in item["stages"]], ensure_ascii=False
            )
            if item["stages"]
            else None,
            status=SessionStatus.FINISHED.value if item["finished"] else SessionStatus.ACTIVE.value,
            summary=item.get("summary"),
            created_at=created_at,
            finished_at=created_at + timedelta(hours=1) if item["finished"] else None,
        )
        db.add(session)
        db.flush()
        for seq, stage, question, answer, score, review, skipped in item["qas"]:
            db.add(
                InterviewQa(
                    session_id=session.id,
                    seq=seq,
                    stage=stage.value,
                    question=question,
                    answer=answer,
                    score=score,
                    review=review,
                    skipped=skipped,
                    created_at=created_at + timedelta(minutes=seq),
                )
            )
    db.flush()
    return len(INTERVIEWS)


def _add_experiences(db: Session, user_id: int) -> int:
    now = _now()
    for item in EXPERIENCES:
        created_at = now - timedelta(days=item["days_ago"])
        experience = Experience(
            user_id=user_id,
            company=item["company"],
            position=item["position"],
            source=item["source"],
            original_text=item["original_text"],
            item_count=len(item["items"]),
            created_at=created_at,
        )
        db.add(experience)
        db.flush()
        db.add_all(
            ExperienceItem(
                experience_id=experience.id,
                question=question,
                answer_points=answer,
                source_type=ExperienceItemSource.LLM_EXTRACT.value,
                created_at=created_at,
            )
            for question, answer in item["items"]
        )
    db.flush()
    return len(EXPERIENCES)


def _pick_questions(db: Session, *, count: int, qtype: QuestionType | None = None) -> list[int]:
    """从题库取若干道不同的题（错题 `UNIQUE(user_id, question_id)` 要求不重复）。"""
    stmt = select(Question.id).order_by(Question.id)
    if qtype is not None:
        stmt = stmt.where(Question.qtype == qtype.value)
    return list(db.scalars(stmt.limit(count)))


def _add_wrong_questions(db: Session, user_id: int) -> int:
    """错题：题库题 + 面试知识点新建题 + 选择题形态，覆盖来源与复习档位。"""
    now = _now()
    picked = _pick_questions(db, count=4)
    choice_picked = _pick_questions(db, count=1, qtype=QuestionType.CHOICE)
    assert len(picked) == 4 and len(choice_picked) == 1, "题库题数不足——请先启动一次服务导入种子"

    for question_id, item in zip(picked, WRONG_QUESTIONS[:4]):
        db.add(
            WrongQuestion(
                user_id=user_id,
                question_id=question_id,
                source_type=item["source"].value,
                next_review_at=now - timedelta(days=item["due_in_days"]),
                mastered_at=now if item["mastered"] else None,
            )
        )

    # INTERVIEW 形态：面试知识点入本——新建一道 AI_GENERATED 题再挂错题
    interview_q = Question(
        stack=INTERVIEW_WRONG_QUESTION["stack"].value,
        direction=INTERVIEW_WRONG_QUESTION["direction"].value,
        content=INTERVIEW_WRONG_QUESTION["content"],
        answer=INTERVIEW_WRONG_QUESTION["answer"],
        source=QuestionSource.AI_GENERATED.value,
    )
    db.add(interview_q)
    db.flush()
    db.add(
        WrongQuestion(
            user_id=user_id,
            question_id=interview_q.id,
            source_type=WrongSourceType.INTERVIEW.value,
            next_review_at=now,
        )
    )

    # MANUAL 形态：手动添加一道选择题
    db.add(
        WrongQuestion(
            user_id=user_id,
            question_id=choice_picked[0],
            source_type=WrongSourceType.MANUAL.value,
            next_review_at=now + timedelta(days=3),
        )
    )
    db.flush()
    return len(WRONG_QUESTIONS)


def _add_practice(db: Session, user_id: int) -> int:
    """陪练：已完成带结算 + 追问链进行中；另附领域掌握度账本。"""
    now = _now()
    for item in PRACTICE_SESSIONS:
        question_id = db.scalar(
            select(Question.id).where(Question.direction == item["direction"].value).limit(1)
        )
        assert question_id is not None, (
            f"题库缺少方向 {item['direction'].value} 的题——请先导入种子"
        )
        started_at = now - timedelta(days=item["days_ago"])
        session = PracticeSession(
            user_id=user_id,
            question_id=question_id,
            mode=item["mode"].value,
            status=(
                PracticeSessionStatus.FINISHED.value if item["finished"]
                else PracticeSessionStatus.RUNNING.value
            ),
            overall_score=item["overall_score"],
            break_face=item["break_face"].value if item["break_face"] else None,
            hint_count=item["hint_count"],
            passed=item["passed"],
            started_at=started_at,
            finished_at=started_at + timedelta(minutes=12) if item["finished"] else None,
        )
        db.add(session)
        db.flush()
        for round_index, kind, _q, answer, score, review in item["records"]:
            db.add(
                PracticeRecord(
                    user_id=user_id,
                    question_id=question_id,
                    session_id=session.id,
                    round_index=round_index,
                    round_kind=kind.value,
                    user_answer=answer,
                    score=score,
                    review=review,
                    created_at=started_at + timedelta(minutes=3 * round_index),
                )
            )
    for stack, direction, mastery, answered, covered in DOMAIN_MASTERY:
        db.add(
            DomainMastery(
                user_id=user_id,
                stack=stack.value,
                direction=direction.value,
                mastery=mastery,
                answered_count=answered,
                covered_count=covered,
                last_practiced_at=now - timedelta(days=1),
            )
        )
    db.flush()
    return len(PRACTICE_SESSIONS)


# ---------- 校招情报（公共数据，不按账号） ----------


def _add_campus_events(db: Session) -> int:
    """校招情报：信息源配置 + 宣讲会 / 双选会（TALK / FAIR、含「已变更」与已过期、单 / 多来源合并）。"""
    db.execute(delete(CampusEvent))
    db.execute(delete(CrawlSource))
    db.flush()

    now = _now()
    db.add_all(
        [
            CrawlSource(
                school_name="南京理工大学",
                system_type=CrawlSystemType.JOB91.value,
                domain="https://njust.91job.org.cn",
                params=json.dumps({"xxdm": "10288"}),
                enabled=1,
                last_crawl_at=now - timedelta(hours=2),
                last_status=CrawlStatus.OK.value,
                created_at=now - timedelta(days=30),
            ),
            CrawlSource(
                school_name="重庆大学",
                system_type=CrawlSystemType.BYSJY.value,
                domain="https://cqu.edu.cn",
                params=json.dumps({"panel_name": "宣讲会", "panel_id": "1"}),
                enabled=1,
                last_crawl_at=now - timedelta(hours=2),
                last_status=CrawlStatus.OK.value,
                created_at=now - timedelta(days=30),
            ),
            CrawlSource(
                school_name="东南大学",
                system_type=CrawlSystemType.JYSD.value,
                domain="https://seu.jysd.com",
                params=None,
                enabled=0,
                last_crawl_at=now - timedelta(days=3),
                last_status=CrawlStatus.BLOCKED.value,
                last_error="robots.txt 明确禁止抓取，按合规要求停止该源",
                created_at=now - timedelta(days=30),
            ),
        ]
    )

    today = date.today()
    rows = [
        # (标题, 公司, 距今天数, 时刻, 地点, 专业要求, 类型, 来源站点, 状态, 变更距今年数)
        ("华为 2027 届校园宣讲会", "华为技术有限公司", 1, 14, "学术交流中心报告厅", "计算机 / 软件工程 / 电子信息", InfoType.TALK.value, "njust.91job.org.cn,cqu.edu.cn", InfoStatus.ACTIVE.value, None),
        ("中国电子科技集团专场双选会", "中国电子科技集团有限公司", 2, 9, "体育馆", "计算机 / 自动化", InfoType.FAIR.value, "njust.91job.org.cn", InfoStatus.ACTIVE.value, None),
        ("字节跳动校园宣讲会（改期）", "北京字节跳动科技有限公司", 3, 16, "大学生活动中心", "计算机 / 数学", InfoType.TALK.value, "cqu.edu.cn", InfoStatus.CHANGED.value, 5,
         ),
        ("国家电网专场宣讲会", "国家电网有限公司", 5, 10, "第一教学楼 101", "电气工程 / 计算机", InfoType.TALK.value, "seu.jysd.com", InfoStatus.ACTIVE.value, None),
        ("腾讯游戏校园行", "深圳市腾讯计算机系统有限公司", 7, 15, "大学生活动中心报告厅", "计算机 / 数字媒体", InfoType.TALK.value, "cqu.edu.cn,njust.91job.org.cn", InfoStatus.ACTIVE.value, None),
        ("小米集团宣讲会（已过期）", "小米科技有限责任公司", -6, 14, "第二教学楼 201", "计算机 / 通信", InfoType.TALK.value, "njust.91job.org.cn", InfoStatus.EXPIRED.value, None),
        ("苏宁易购双选会（已过期）", "苏宁易购集团股份有限公司", -30, 9, "体育馆", None, InfoType.FAIR.value, "cqu.edu.cn", InfoStatus.EXPIRED.value, None),
    ]
    for index, (title, company, days, hour, location, major, info_type, site, status, changed_hours) in enumerate(rows):
        event_date = datetime.combine(today, time(hour, 0)) + timedelta(days=days)
        db.add(
            CampusEvent(
                title=title,
                company=company,
                event_date=event_date,
                location=location,
                source_url=f"https://njust.91job.org.cn/sub-station/lectureDetail?xjhid=demo{index}",
                info_type=info_type,
                major_req=major,
                source_site=site,
                dedup_key=processor.dedup_key(company, title, event_date),
                content_hash=processor.content_hash(
                    RawItem(title=title, event_date=event_date, info_type=info_type, company=company, location=location, major_req=major)
                ),
                status=status,
                first_seen_at=now - timedelta(days=20 - index),
                last_seen_at=now - timedelta(hours=2),
                changed_at=(now - timedelta(hours=changed_hours)) if changed_hours else None,
            )
        )
    db.flush()
    return len(rows)


def _add_job_postings(db: Session) -> int:
    """校招情报：公共岗位（`user_id=0` 自动抓取）——覆盖高分命中 / 已变更 / 已过期 / 多来源合并。

    只清公共行（`user_id=0`）：开发者自己投喂的私有岗位（`FEED`）不属演示数据，不动。
    """
    db.execute(delete(JobPosting).where(JobPosting.user_id == SYSTEM_USER_ID))
    db.flush()

    now = _now()
    rows = [
        # (标题, 公司, 城市, 学历, 专业, 薪资, 类型, 截止距今天数, 来源站点, 状态, 变更距今年数, 首次入库距今天数)
        ("Java 后端开发工程师", "华为技术有限公司", "南京", "硕士", "计算机科学与技术", "25-35K·14薪", JobType.CAMPUS.value, 20, "njust.91job.org.cn", InfoStatus.ACTIVE.value, None, 0),
        ("后端开发工程师（实习）", "北京字节跳动科技有限公司", "南京", "本科", "计算机科学与技术", "300/天", JobType.INTERN.value, 12, "cqu.edu.cn,njust.91job.org.cn", InfoStatus.ACTIVE.value, None, 0),
        ("前端开发工程师", "深圳市腾讯计算机系统有限公司", "南京", "本科", "计算机科学与技术", "20-30K", JobType.CAMPUS.value, 25, "cqu.edu.cn", InfoStatus.ACTIVE.value, None, 1),
        ("数据开发工程师", "美团", "上海", "本科", None, "22-32K", JobType.CAMPUS.value, 15, "seu.jysd.com", InfoStatus.ACTIVE.value, None, 2),
        ("Java 后端开发工程师", "中国电子科技集团有限公司", "南京", "硕士", "计算机科学与技术", "18-25K", JobType.CAMPUS.value, 30, "njust.91job.org.cn", InfoStatus.CHANGED.value, 4, 3),
        ("Java 开发工程师（已过期）", "小米科技有限责任公司", "南京", "本科", "计算机", "20-28K", JobType.CAMPUS.value, -8, "njust.91job.org.cn", InfoStatus.EXPIRED.value, None, 40),
    ]
    for index, (title, company, city, edu, major, salary, job_type, days, site, status, changed_hours, seen_days) in enumerate(rows):
        deadline = now + timedelta(days=days)
        row = JobPosting(
            user_id=SYSTEM_USER_ID,
            title=title,
            company=company,
            city=city,
            edu_req=edu,
            major_req=major,
            salary_text=salary,
            job_type=job_type,
            deadline=deadline,
            source_site=site,
            source_url=f"https://{site.split(',')[0]}/job/demo{index}",
            ingest_source=IngestSource.AUTO.value,
            dedup_key=processor.posting_dedup_key(company, title, city),
            status=status,
            first_seen_at=now - timedelta(days=seen_days),
            last_seen_at=now - timedelta(hours=2),
            changed_at=(now - timedelta(hours=changed_hours)) if changed_hours else None,
        )
        row.content_hash = processor.posting_content_hash(row)
        db.add(row)
    db.flush()
    return len(rows)


def _add_subscriptions(db: Session, user_id: int) -> int:
    """订阅规则（账号私有）：两条演示规则——跑一次每日任务后概览即出现「订阅命中」提醒。"""
    now = _now()
    rules = [
        # (名称, 关键词, 城市, 信息类型)
        ("后端岗位", ["后端"], None, ["JOB"]),
        ("南京宣讲会", None, ["南京"], ["TALK"]),
    ]
    for name, keywords, cities, info_types in rules:
        db.add(
            Subscription(
                user_id=user_id,
                name=name,
                keywords=json.dumps(keywords, ensure_ascii=False) if keywords else None,
                companies=None,
                cities=json.dumps(cities, ensure_ascii=False) if cities else None,
                info_types=json.dumps(info_types, ensure_ascii=False),
                enabled=1,
                created_at=now - timedelta(days=10),
            )
        )
    db.flush()
    return len(rules)


def _add_agent_conversations(db: Session, user_id: int) -> int:
    """全局 Agent 会话（三种形态见定义处注释）。放在数据装载最后——查询工具的结果要读全量数据。"""
    now = _now()
    for item in AGENT_CONVERSATIONS:
        started_at = now - item["ago"]
        conversation = AgentConversation(
            user_id=user_id, title=item["title"], created_at=started_at, updated_at=started_at
        )
        db.add(conversation)
        db.flush()
        for role, offset_minutes, content, tool_name, tool_args in item["messages"]:
            if callable(content):
                content = content(db, user_id)  # 查询类 TOOL 结果按当前库内数据生成
            sent_at = started_at + timedelta(minutes=offset_minutes)
            db.add(
                AgentMessage(
                    conversation_id=conversation.id,
                    role=role.value,
                    content=content,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    created_at=sent_at,
                )
            )
            conversation.updated_at = sent_at
    db.flush()
    return len(AGENT_CONVERSATIONS)


def _load_business_data(db: Session, user_id: int, *, with_llm: bool = True) -> dict[str, int]:
    """把整套业务数据写入指定账号（调用方负责清场策略）。"""
    _fill_profile(db, user_id)
    if with_llm:
        _add_llm_config(db, user_id)
    return {
        "applications": _add_applications(db, user_id),
        "jd_reports": _add_jd_reports(db, user_id),
        "interviews": _add_interviews(db, user_id),
        "experiences": _add_experiences(db, user_id),
        "wrong_questions": _add_wrong_questions(db, user_id),
        "practice_sessions": _add_practice(db, user_id),
        "campus_events": _add_campus_events(db),  # 公共数据（信息源 + 宣讲会/双选会），随全套数据一并重建
        "job_postings": _add_job_postings(db),  # 公共岗位（步骤 22），同上
        "subscriptions": _add_subscriptions(db, user_id),  # 订阅规则（账号私有，步骤 22）
        "agent_conversations": _add_agent_conversations(db, user_id),  # 步骤 18/19
        "profiles": len(PROFILE),
    }


# ---------- 入口 ----------


def reset_and_load(db: Session) -> dict[str, int]:
    """重建演示数据（先删后建，幂等）。返回各表写入条数。"""
    _delete_demo_users(db)

    demo = _create_account(db, DEMO_USERNAME, "演示账号")
    summary = _load_business_data(db, demo.id)

    # 第二个账号：只放一条投递，用于验证「换账号后看不到别人的数据」
    other = _create_account(db, SECOND_USERNAME, "隔离验证账号")
    db.add(
        Application(
            user_id=other.id,
            company="另一个账号的公司",
            position="后端开发",
            jd_text="岗位职责：\n1. 验证跨账号隔离用的投递。",
            status=ApplicationStatus.APPLIED.value,
            applied_at=_now() - timedelta(days=4),
        )
    )

    db.commit()
    return summary


def reset_for_user(db: Session, username: str) -> dict[str, int]:
    """重建指定账号的业务数据（保留其 AI 配置），账号与密码不动。"""
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise SystemExit(f"账号 {username} 不存在——--user 只对已注册账号重建，不新建账号")
    _delete_account_data(db, [user.id], keep_llm=True)
    summary = _load_business_data(db, user.id, with_llm=False)
    db.commit()
    return summary


# 验证 / 调试过程中产生的临时账号名前缀。`--purge` 时按前缀清除，**不动其他账号**
# （开发者自己的账号、演示账号都不受影响）。
_TEST_ACCOUNT_PREFIXES = ("link_", "link9", "empty_", "diag_", "lay_", "step", "tmp_", "check_", "walk")


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
    _delete_account_data(db, ids)
    db.execute(delete(User).where(User.id.in_(ids)))
    db.commit()
    return [u.username for u in victims]


def _print_summary(target: str, summary: dict[str, int]) -> None:
    print(
        f"数据已重建（{target}）：\n"
        f"  投递 {summary['applications']} 条（五种状态与各类时间场景，均带 JD）\n"
        f"  JD 报告 {summary['jd_reports']} 条（关联投递 / 独立 / 半成品各 1）\n"
        f"  面试 {summary['interviews']} 场（已结束带总结 / 进行中 / 存量无阶段化）\n"
        f"  面经 {summary['experiences']} 篇（含条目；1 篇未填公司）\n"
        f"  错题 {summary['wrong_questions']} 条（含面试知识点与选择题形态）\n"
        f"  陪练 {summary['practice_sessions']} 场（已完成结算 / 追问链进行中）+ 掌握度 4 域\n"
        f"  校招情报 {summary['campus_events']} 条（TALK / FAIR，「已变更」与已过期各覆盖）+ 信息源 3 个\n"
        f"  校招岗位 {summary['job_postings']} 条（公共；高分命中 / 已变更 / 已过期 / 多来源合并）+ 订阅规则 {summary['subscriptions']} 条\n"
        f"  Agent 会话 {summary['agent_conversations']} 个（查询工具执行 / 写操作确认卡 / 多轮纯文本）\n"
        f"  画像 {summary['profiles']} 个字段 + 经历条目 {len(PROFILE_EXPERIENCES)} 条"
    )


def main() -> None:
    purge = "--purge" in sys.argv
    user_arg = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--user=")), None)
    if user_arg is None and "--user" in sys.argv and sys.argv.index("--user") + 1 < len(sys.argv):
        user_arg = sys.argv[sys.argv.index("--user") + 1]  # 也支持 `--user lsjtest` 的空格写法

    init_db()  # 幂等：建表 + 系统配置 + 题库种子（题库不全会导致错题无题可用）
    with SessionLocal() as db:
        purged = purge_test_accounts(db) if purge else []
        if user_arg:
            summary = reset_for_user(db, user_arg)
            _print_summary(f"账号 {user_arg}，AI 配置已保留", summary)
        else:
            summary = reset_and_load(db)
            _print_summary(
                f"账号 {DEMO_USERNAME} / {SECOND_USERNAME}（密码 {DEMO_PASSWORD}）", summary
            )
    if purge:
        print(f"  已清除临时账号 {len(purged)} 个：{'、'.join(purged) if purged else '（无）'}")


if __name__ == "__main__":
    main()
