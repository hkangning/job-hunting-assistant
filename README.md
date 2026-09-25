# 个人求职助手（Personal Job Hunter）

《软件工程职业实践》课程设计项目 —— 面向大四学生的求职全流程 AI 助手：**投递管理 → JD 匹配分析 → 笔试备战 → AI 模拟面试 → 面经复盘**。

产品形态是**工作台**（结构化页面 + 数据看板），不是聊天框套壳大模型：AI 能力嵌入每个操作流（录入投递、分析 JD、点评答题），并提供全局 Agent 悬浮球作为快捷入口。

其中面试模块定位为 **AI 面试教练**——服务求职者本人（而非替企业筛选）：一场 N 题的「模拟面试」与一道题反复练的「练习模式」共用同一套底座，并从语音作答的分句时间轴中提取语速、停顿、填充词等**表达力指标**，与 AI 的内容点评**分列呈现**；练习记录可跨次对比进步曲线。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.x / SQLite（WAL） |
| 账号 | 多账号：JWT 鉴权（1 天 / 30 天免登录）+ bcrypt 密码哈希，**数据按账号隔离**，每账号独立配置 AI 供应商 |
| LLM | 多供应商+模型两级可配置（12 家：DeepSeek / 智谱 / Kimi / 通义千问 / 豆包 / OpenAI / Gemini / Claude / Grok / OpenRouter / Ollama / 自定义），模型列表动态拉取保持最新，SSE 流式 |
| Agent | 手写实现：意图路由 + 工具注册表 + 画像记忆（不用 LangChain） |
| 语音（P2） | 转写：**FunASR 本地流式模型**（进程内、不限时长、不出网；讯飞云端为备选）；播报：**edge-tts**（中文音色 20+）。前端 VAD 静音自动断句，支持长时长连续作答 |
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
- [ ] 开发（按开发计划 27 个步骤 / 5 个阶段推进，不预设时间节点；当前：步骤 1~5（后端）与步骤 7（前端）已完成——步骤 5 账号与鉴权（后端）、步骤 7 账号体系（前端：入场动画 / 登录注册 / 用户菜单 / 个人中心）均已落地，下一步做步骤 6 AI 供应商配置（后端））

## 目录结构

```
job-hunting-assistant/
├── docs/        # 文档目录（开发的唯一依据来源，开发前必须先看这里）
│   ├── 00-项目介绍/    项目介绍（选题原因/选型理由/分工）
│   ├── 01-需求文档/    需求规格说明书
│   ├── 02-设计文档/    系统设计文档 + 项目结构
│   ├── 03-数据库/      数据库设计文档
│   ├── 04-接口文档/    接口文档
│   ├── 05-测试文档/    测试计划
│   ├── 06-开发计划/    开发计划
│   └── 07-工作日志/    后端 / 前端工作日志 + 问题记录
├── backend/     # 后端（FastAPI）
├── frontend/    # 前端（Vue 3）
└── README.md    # 本文件
```

## 工作约定

1. 开发严格按照 `docs/` 目录下的文档执行，严禁自由发挥。
2. 文档先行：先定稿文档，再动代码；改需求先改文档。
3. 测试随开发：LLM 调用全 mock，测试离线可跑。
4. 环境变量：复制 `backend/.env.example` 为 `.env` 填入 `APP_SECRET_KEY`（JWT 签名与 Key 加密的主密钥，必填）及供应商 API Key（可选，登录后在 **AI 配置页**填更灵活，存库优先）；`.env` 已 gitignore，严禁提交。

## 快速开始

> 命令以 **Windows PowerShell** 为准（VS Code 终端直接用）。Linux / macOS：路径 `\` 换成 `/`，激活改用 `source .venv/bin/activate`。

### 后端

```powershell
cd backend
python -m venv .venv                            # 首次：创建虚拟环境（已建过可跳过）
.\.venv\Scripts\Activate.ps1                    # 激活（成功后命令行前显示 (.venv)）
pip install -r requirements.txt                 # 首次：安装依赖
python -m uvicorn app.main:app --port 8000      # 启动 → http://127.0.0.1:8000/api/v1/health
```

- 激活时提示"禁止运行脚本" → 先执行一次 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- `python` 提示找不到 → 系统未把 Python 加入 PATH，改用其安装目录全路径，如 `C:\Python313\python.exe -m venv .venv`
- 不想每次激活（每个新终端都要重新激活）→ 把 `pip` / `python` 换成 `.\.venv\Scripts\python.exe -m pip` / `.\.venv\Scripts\python.exe`

### 前端

```powershell
cd frontend
npm -v                                          # 需 ≥ 11.12.1（升级方式见下方注意）
npm install
npm run dev                                     # http://localhost:5173
```

- **npm 需 ≥ 11.12.1**（Node 需 `^20.19.0 || >=22.12.0`，随 Vite 8）：低版本 npm（实测 11.6.1）会给锁文件里 optional 平台包写冗余的 `"dev": true` / `"peer": true` 标记，导致两人的 `package-lock.json` 反复互改（该差异不影响装出的依赖，属纯元数据噪声）；`frontend/.npmrc` 已设 `engine-strict=true`，版本不符时 `npm install` 会报 `EBADENGINE` 拒绝安装——这是有意的版本统一措施，请升级 npm 而非绕过
- **升 npm 前先确认 Node 版本**：npm 12.x（当前 12.1.0）自身要求 Node `^22.22.2 || ^24.15.0 || >=26.0.0`，Node 低于此时 `npm install -g npm@latest` 会报 `EBADENGINE` 装不上（实测 Node 24.11.0 被拒）——先升 Node，或改装 `npm install -g npm@11.12.1`（两者产出的锁文件经实测逐行一致，均满足本工程要求）

### 跑测试（`backend/` 目录、虚拟环境已激活）

```powershell
pytest                                          # 全量（LLM 全 mock，离线可跑）
```

### 本地地址一览（服务启动后）

| 服务 | 地址 | 说明 |
|---|---|---|
| 后端接口前缀 | http://127.0.0.1:8000/api/v1 | 所有 REST 接口的统一前缀 |
| **在线接口文档** | **http://127.0.0.1:8000/docs** | Swagger UI：展开接口 → `Try it out` → `Execute`，直接在页面上发请求调试 |
| 在线接口文档（只读） | http://127.0.0.1:8000/redoc | 同一份文档的只读版，排版适合截图 |
| 健康检查 | http://127.0.0.1:8000/api/v1/health | 返回 `{"code":0,...}` 表示服务与数据库正常（免鉴权） |
| 前端页面 | http://localhost:5173 | Vite 开发服务器（`npm run dev`）；未登录会先进入场动画 → `/login` |

> `/docs` 与 `/redoc` 由 FastAPI 依据代码中的路由与数据模型自动生成，改代码后自动更新；接口的业务规则（状态机、错误码含义等）以 `docs/04-接口文档/接口文档.md` 为准。
>
> 在 `/docs` 里调业务接口需先登录：`POST /auth/login` 拿到 `token` → 点页面右上角 **Authorize** → 粘贴 token 本体（不必手写 `Bearer`，Swagger 自动补）→ 之后所有请求自动带鉴权头。

**首次使用**：打开 http://localhost:5173 → 入场动画后进入**注册页**建账号（用户名 + 密码 ≥ 6 位）→ 自动登录进入今日概览 → 右上角头像下拉进入 **AI 配置**页，选供应商与模型（如 DeepSeek 的 deepseek-flash）→ 填 API Key → 连通性测试 → 保存，即可使用全部 AI 功能。

**账号说明**：投递、面经、错题、AI 配置等数据**按账号隔离**，换账号登录互不可见（题库、宣讲会为全站共享）；登录时勾选「30 天免登录」可保持 30 天，不勾选为 1 天。
