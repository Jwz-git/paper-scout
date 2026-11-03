# Paper Scout

Paper Scout 是一个本地单用户的 AI 科研文献调研原型工具。它将**对话式交互**与**后台显式状态机**解耦，支持通过自然语言对话发起调研、动态补充条件与追问资料，自动化执行 arXiv 检索、PDF 文本提取，并生成附带精确原文证据的阶段性 Markdown 调研报告。

> **当前阶段声明**：本项目当前为资料收集与阶段性报告原型，重点保证检索/阅读流程的可控性、可中断恢复与证据可追溯性；尚未实现深度的跨论文语义分析、实验条件自动比对及 Word/PDF 导出。

---

## 核心特性

- **对话式调研协作**：主界面采用对话时间线，通过自然语言描述目标（如“检索多智能体通信近三年工作”）；支持在执行中发送补充指令（在安全检查点重新规划并继续同次运行），或切换至“仅追问已有资料”模式。
- **可追溯的事实证据链**：区分元数据、摘要与实际解析的 PDF 页面；关键报告结论关联精确的原文摘录、字符区间与来源快照，拒绝凭空臆造。
- **多模型供应商与协议**：支持 OpenAI Chat Completions、OpenAI Responses 和 Anthropic Messages 协议；支持本地管理多家供应商凭据、拉取或手动输入模型清单，并在对话中按需切换。
- **严格的资源与执行预算**：显式状态机限制单次运行的轮次、检索量、PDF 下载/解析时限（单篇最大 25 MiB / 50 页 / 10 秒超时）与外部调用次数，杜绝无限死循环与意外消耗。
- **本地优先与隐私安全**：单用户架构，运行数据与凭据均保存在本地（SQLite 与本地 JSON 配置），支持会话重命名、软删除回收站与导出。

---

## 技术架构

- **后端**：Python 3.9+ / FastAPI / SQLite / 显式状态机执行引擎
- **前端**：Vue 3 / TypeScript / Vite
- **适配层**：arXiv API 客户端、PDF 文本解析器、标准化 LLM 协议适配器

---

## 快速上手

### 1. 环境准备

确保本机已安装：
- Python 3.9+
- Node.js 18+ 与 npm

### 2. 后端启动

```bash
# 克隆仓库并进入根目录
git clone <repo-url>
cd paper-scout

# 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Windows 用户: .venv\Scripts\activate

# 安装固定依赖
pip install -r backend/requirements-lock.txt

# 运行定向回归测试（离线运行，无需外网）
PYTHONPATH=. pytest -q

# 启动本地后端服务（默认监听 127.0.0.1:8000）
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

### 3. 前端启动

在另一个终端窗口中进入 `frontend/` 目录：

```bash
cd frontend

# 安装依赖
npm ci

# 启动前端开发服务器（开发端口 5173，API 自动代理至后端 8000）
npm run dev
```

启动完成后，在浏览器中访问：`http://127.0.0.1:5173`。

---

## 配置说明

### AI 服务配置（推荐在 Web 界面完成）

1. 启动并打开前端页面后，点击左下角 **设置 → AI服务**。
2. 添加供应商：选择协议（`openai_chat`、`openai_responses` 或 `anthropic_messages`），填写 Base URL 及 API Key。
3. 点击“获取可用模型”或手动录入模型 ID。
4. 在对话输入框下方的模型选择菜单中，选中目标供应商与型号即可开始使用。

> 凭据保存在本地数据目录下的 `model-settings.json`（权限 600），前端不会回显或持久化明文 API Key。

### 环境变量配置（可选）

如需无前端或初始化时通过环境变量指定模型，可复制模板：

```bash
cp .env.example .env
```

核心配置项说明：
- `LLM_PROTOCOL`: 接口协议类型（`openai_chat` | `openai_responses` | `anthropic_messages`）
- `LLM_BASE_URL`: API 基础地址（如 `https://api.openai.com/v1`）
- `LLM_MODEL`: 使用的模型 ID
- `LLM_API_KEY`: 供应商 API Key
- `DATA_DIR`: 可选，本地运行数据存放目录（默认为仓库根目录下的 `data/`）
- `ARXIV_RATE_LIMIT_SECONDS`: arXiv 请求间隔（默认 3.0 秒）

> 若所有 LLM 配置均为空，系统将以**无模型资料检索模式**启动，仅支持基于关键词的简单检索与资料展示，无法自动理解复杂语义补充。

---

## 项目文档导航

深入的设计规范与架构细节请参阅 `docs/` 目录：

| 文档 | 主要内容 |
| --- | --- |
| [需求与验收](docs/01-requirements.md) | 产品功能边界、核心需求与验收指标 |
| [系统架构](docs/02-architecture.md) | 分层职责、状态流转与单机部署模型 |
| [数据与接口](docs/03-data-and-api.md) | 数据模型、会话执行语义与 RESTful API 契约 |
| [智能体流程](docs/04-agent-workflow.md) | 调研工作流、检查点机制与限制阈值 |
| [开发与评估](docs/05-development-and-evaluation.md) | 本地测试策略、人工评价标准与边界 |
| [决策记录](docs/06-decisions.md) | 关键技术选型依据与待定考量 |
| [外部服务接入](docs/07-external-services.md) | arXiv 与各大模型协议兼容性参考 |
