# 个人求职助手（Personal Job Hunter）

《软件工程职业实践》课程设计项目 —— 面向大四学生的求职全流程 AI 助手：**投递管理 → JD 匹配分析 → 笔试备战 → AI 模拟面试 → 面经复盘**。

产品形态是**工作台**（结构化页面 + 数据看板），不是聊天框套壳大模型：AI 能力嵌入每个操作流（录入投递、分析 JD、点评答题），并提供全局 Agent 悬浮球作为快捷入口。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.x / SQLite（WAL） |
| LLM | 多供应商+模型两级可配置（DeepSeek 默认；智谱/Kimi/硅基流动/自定义 OpenAI 兼容接口），模型列表动态拉取保持最新，SSE 流式 |
| Agent | 手写实现：意图路由 + 工具注册表 + 画像记忆（不用 LangChain） |
| 语音（P2） | 讯飞语音听写 + 浏览器 speechSynthesis |
| 前端 | Vue 3 + Vite + Element Plus + Pinia + Vue Router |
| 定时 | APScheduler |
| 测试 | pytest + FastAPI TestClient（LLM 调用全 mock） |

## 团队成员

| 成员 | 职责 |
|---|---|
| 胡康宁 | 后端开发、数据库设计、AI 供应商接入 |
| 卢世君 | 前端开发、测试用例编写与执行 |

## 项目状态

- [x] 选题确定（个人求职助手）
- [x] 文档定稿（项目介绍/需求/设计/数据库/接口/测试/开发计划）
- [ ] 开发（按开发计划步骤 1~11 推进，不预设时间节点）

## 目录结构

```
Keshe1/
├── docs/        # 文档目录（开发的唯一依据来源，开发前必须先看这里）
│   ├── 00-项目介绍/    项目介绍（选题原因/选型理由/分工）
│   ├── 01-需求文档/    需求规格说明书
│   ├── 02-设计文档/    系统设计文档 + 项目结构
│   ├── 03-数据库/      数据库设计文档
│   ├── 04-接口文档/    接口文档
│   ├── 05-测试文档/    测试计划
│   └── 06-开发计划/    开发计划
├── backend/     # 后端（FastAPI）
├── frontend/    # 前端（Vue 3）
└── README.md    # 本文件
```

## 工作约定

1. 开发严格按照 `docs/` 目录下的文档执行，严禁自由发挥。
2. 文档先行：先定稿文档，再动代码；改需求先改文档。
3. 测试随开发：LLM 调用全 mock，测试离线可跑。
4. 环境变量：复制 `backend/.env.example` 为 `.env` 填入供应商 Key（已 gitignore，严禁提交）；也可在系统设置页配置。

## 快速开始

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# 前端
cd frontend
npm install
npm run dev        # http://localhost:5173
```

首次使用：进入系统设置页，选择 AI 供应商与模型（如 DeepSeek 的 deepseek-flash）→ 填写 API Key → 连通性测试 → 保存，即可使用全部 AI 功能。
