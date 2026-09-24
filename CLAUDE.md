# CLAUDE.md

个人求职助手 —— 《软件工程职业实践》课程设计项目。

## 分支协作约定

单仓库 + 分支隔离，仓库根下 `docs/`、`backend/`、`frontend/` 三个平级子目录（详见 [docs/02-设计文档/项目结构.md](docs/02-设计文档/项目结构.md)）。

| 分支 | 承担内容 | 负责人 |
|---|---|---|
| `backend` | 后端代码（`backend/`）+ 公共文件副本 | 胡康宁 |
| `frontend` | 前端代码（`frontend/`）+ 公共文件副本 | 卢世君 |
| `main` | 汇合分支（三目录齐全，可运行完整系统） | — |

### 开发循环

这是一个两人小项目，按**来回合并**的节奏走，不搞长周期分支：

1. **各自开发**：后端只动 `backend/`，前端只动 `frontend/`，互不干涉。
2. **来回合并**：定期 `git fetch origin` 后，把对方分支合并进自己的分支，尽早暴露冲突。
   ```bash
   git fetch origin
   git merge origin/backend     # 在 frontend 分支上；反向则在 backend 分支上 merge origin/frontend
   ```
3. **验证**：合并后必须验证能跑通——后端 `cd backend && pytest`，前端 `cd frontend && npm run dev` 页面可用。
4. **没问题再进 main**：两侧都稳定后合入汇合分支。
   ```bash
   git checkout main && git merge backend && git merge frontend && git push origin main
   ```

### 公共文件

`docs/`、`README.md`、`.gitignore` 在两条分支上**各持一份副本**，改动前先知会对方，改后相互拉取同步：

```bash
git fetch origin
git checkout origin/backend -- docs README.md .gitignore
git add -A && git commit -m "文档同步：<变更内容>"
```

**冲突时一律以后端最新版为准**（后端侧文档迭代最快，是权威口径）。

分支独有文件天然分属不同子目录，合并时自动并存。不入库：`backend/.venv/`、`frontend/node_modules/`、`*.db`、`frontend/dist/`、`.env`（真实密钥）。

## 文档规范

- `docs/` 是开发的**唯一依据来源**，开发前必须先看文档。
- **文档先行**：先定稿文档再动代码；改需求先改文档，再改代码。
- 严格按文档执行，严禁实现文档中未约定的功能。
- 文档间有依赖链（需求 → 设计 → 数据库/接口 → 测试 → 开发计划），改任一份后按下游方向检查是否需同步。

## 开发规范

- **提交信息用简体中文**，一次提交对应一个文档或一个功能步骤。
- 测试随开发：LLM 调用**全 mock**，测试离线可跑。
- 环境变量：复制 `backend/.env.example` 为 `.env` 填入供应商 Key（已 gitignore，严禁提交）。
