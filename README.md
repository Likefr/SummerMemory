<div align="center">

# 🧠 SummerMemory

### 自建 AI 记忆系统 — 让 AI 拥有持久记忆与知识图谱

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Vue 3](https://img.shields.io/badge/Vue-3.x-42b883.svg)](https://vuejs.org/)
[![PostgreSQL + pgvector](https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg)](https://github.com/pgvector/pgvector)

**[🌐 在线 Demo](https://ai.likefr.com/graph)** · **[📖 API 文档](skill/references/api-docs.md)** · **[🏗️ 架构说明](skill/references/architecture.md)**

</div>

---

## ✨ 项目简介

SummerMemory 是一个**完全自托管**的 AI 记忆管理系统。它能将文本、笔记、对话等非结构化内容自动向量化并存储，支持**语义搜索**和**知识图谱可视化**，让 AI 助手拥有持久、可检索的长期记忆。

无论是个人知识管理、AI 助手记忆增强，还是构建 RAG（检索增强生成）系统，SummerMemory 都能提供轻量、高效的基础设施。

---

## 🏗️ 系统架构

```
┌─────────────┐     ┌──────────────────┐     ┌───────────────┐
│   Frontend   │────▶│   Backend API    │────▶│  PostgreSQL   │
│  (Vue 3 +    │◀────│  (Python HTTP)   │◀────│  + pgvector   │
│  D3/Cosmo)   │     │  Port: 11435     │     │  Port: 5432   │
└─────────────┘     └────────┬─────────┘     └───────────────┘
                             │
                             ▼
                    ┌───────────────┐
                    │    Ollama      │
                    │  Embedding     │
                    │  Port: 11434   │
                    └───────────────┘
```

**核心流程：**
1. **写入**：文本内容 → jieba 分词 + Ollama 向量化 → PostgreSQL（pgvector）存储
2. **搜索**：查询文本 → 向量化 → 向量余弦相似度 + 全文检索（TSVECTOR）混合搜索
3. **图谱**：记忆路径关系 → 力导向图 / Cosmograph GPU 渲染可视化
4. **OpenClaw 集成**：通过 Skill（SKILL.md）将记忆服务接入 AI 助手工作流

---

## 🛠️ 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **后端** | Python 3.10 + http.server | 轻量 HTTP API 服务 |
| **数据库** | PostgreSQL 15 + pgvector | 向量存储 + 关系数据 |
| **向量模型** | Ollama (bge-small-zh-v1.5) | 本地中文语义向量（512维） |
| **中文分词** | jieba | 全文检索分词 |
| **前端** | Vue 3 + Vite | 知识图谱可视化界面 |
| **图谱渲染** | D3.js force-graph / Cosmograph | 力导向图 + GPU 加速 |
| **部署** | Docker Compose | 一键启动全部服务 |
| **AI 集成** | OpenClaw Skill | 命令行工具 + 自动化工作流 |

---

## 🌟 功能特性

- 🔍 **混合搜索** — 向量语义搜索 + PostgreSQL 全文检索，双引擎精准匹配
- 🧠 **自动向量化** — 写入时自动通过 Ollama 生成 Embedding，无需手动处理
- 🕸️ **知识图谱可视化** — 交互式力导向图，支持拖拽、缩放、节点高亮
- 🌐 **多语言界面** — 内置中英文切换（i18n）
- 🔄 **增量更新** — 基于内容 Hash 的变更检测，仅更新变化的内容
- 📊 **统计分析** — 记忆条目统计、活动日志、系统健康检查
- 🐳 **一键部署** — Docker Compose 编排，开箱即用
- 🔒 **完全自托管** — 数据留在本地，无需外部 API 调用
- 🤖 **OpenClaw 集成** — 通过 Skill 将记忆系统无缝接入 AI 助手

---

## 🚀 快速开始

### 前置要求

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- 至少 2GB 可用内存（Ollama 模型加载需要）
- （可选）NVIDIA GPU + nvidia-docker 用于加速向量计算

### 一键部署

```bash
# 1. 克隆仓库
git clone https://github.com/Likefr/SummerMemory.git
cd SummerMemory

# 2. 进入后端目录，启动所有服务
cd backend
docker compose up -d

# 3. 等待 Ollama 启动后，拉取向量模型（首次需要）
docker exec summer-memory-ollama ollama pull quentinz/bge-small-zh-v1.5

# 4. （可选）启动前端可视化
cd ../frontend
npm install
npm run dev
# 访问 http://localhost:5173
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DB_HOST` | `postgres` | 数据库主机 |
| `DB_PORT` | `5432` | 数据库端口 |
| `DB_NAME` | `summer_memory` | 数据库名 |
| `DB_USER` | `postgres` | 数据库用户 |
| `DB_PASSWORD` | `summer2026` | 数据库密码 |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama 服务地址 |
| `OLLAMA_MODEL` | `quentinz/bge-small-zh-v1.5` | 向量模型名称 |

---

## 📁 项目结构

```
SummerMemory/
├── README.md                   ← 你正在看的文件
├── LICENSE                     ← MIT 开源协议
├── .gitignore
│
├── backend/                    ← 🔧 后端服务
│   ├── memory_server.py        ← HTTP API 服务主程序
│   ├── memory_system.py        ← CLI 命令行工具
│   ├── requirements.txt        ← Python 依赖
│   ├── Dockerfile              ← 后端容器构建
│   ├── docker-compose.yml      ← 一键部署编排
│   ├── init-db.sql             ← 数据库初始化（表+索引）
│   └── .gitignore
│
├── frontend/                   ← 🎨 前端可视化
│   ├── src/
│   │   ├── App.vue             ← 根组件
│   │   ├── main.js             ← 入口
│   │   ├── i18n.js             ← 中英文国际化
│   │   ├── style.css           ← 全局样式
│   │   ├── api/memory.js       ← 后端 API 调用
│   │   ├── components/
│   │   │   ├── MemoryGraph.vue ← 知识图谱核心组件
│   │   │   └── HelloWorld.vue  ← 欢迎页
│   │   └── assets/             ← 静态资源
│   ├── public/                 ← 公共资源
│   ├── index.html              ← HTML 模板
│   ├── vite.config.js          ← Vite 构建配置
│   ├── package.json
│   └── .gitignore
│
└── skill/                      ← 🤖 OpenClaw Skill
    ├── SKILL.md                ← Skill 定义文件
    ├── scripts/
    │   ├── install.sh          ← 一键安装脚本
    │   └── init-db.sql         ← 数据库初始化 SQL
    ├── references/
    │   ├── api-docs.md         ← 完整 API 文档
    │   └── architecture.md     ← 系统架构详解
    └── templates/
        ├── docker-compose.yml  ← 部署模板
        └── systemd.service     ← systemd 服务模板
```

---

## 📡 API 文档概要

后端服务运行在 `http://localhost:11435`，主要接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/stats` | 系统统计（记忆总数、最近活动等） |
| `GET` | `/search?query=xxx&limit=5` | 混合搜索（向量 + 全文） |
| `GET` | `/index` | 获取全部记忆索引（图谱数据源） |
| `POST` | `/index` | 写入/更新记忆条目 |
| `DELETE` | `/memory?id=x` | 删除指定记忆 |
| `GET` | `/health` | 服务健康检查 |

> 📖 完整 API 文档见 [skill/references/api-docs.md](skill/references/api-docs.md)

---

## 🤝 OpenClaw 集成

SummerMemory 提供 OpenClaw Skill，可以将记忆系统无缝集成到 AI 助手工作流中：

```bash
# 使用 OpenClaw Skill 安装
# 将 skill/ 目录复制到 ~/.openclaw/workspace/skills/summer-memory/
cp -r skill/ ~/.openclaw/workspace/skills/summer-memory/
```

安装后，AI 助手可以通过 Skill 定义的命令行工具进行记忆的存储、搜索和管理。

---

## 📜 License

本项目基于 [MIT License](LICENSE) 开源。

---

<div align="center">

**Made with ❤️ by [Likefr](https://likefr.com)**

如果这个项目对你有帮助，欢迎 ⭐ Star！

</div>
