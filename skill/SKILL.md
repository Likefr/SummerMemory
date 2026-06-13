---
name: summer-memory
description: "SummerMemory — 自建 AI 记忆系统，混合向量+全文搜索，图谱可视化，支持中文优化。用于记忆存储、语义搜索、知识图谱。"
---

# SummerMemory Skill

🌐 **在线 Demo**: [https://ai.likefr.com/graph](https://ai.likefr.com/graph)

自建 AI 记忆系统：PostgreSQL + pgvector 向量搜索 + Ollama embedding + jieba 中文分词 + BM25 全文搜索。

## 触发条件

- 用户要求搜索记忆、查找相关知识
- 用户要求存储/写入/记录一条记忆
- 用户要求索引文件到记忆系统
- 用户要求查看记忆图谱、活动统计
- 用户提到 "记忆"、"memory"、"remember" 相关操作

## 系统架构

```
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐
│  memory/    │───▶│ memory_system│───▶│   PostgreSQL     │
│  (md files) │    │   .py (CLI)  │    │ + pgvector       │
└─────────────┘    └──────┬───────┘    └────────┬────────┘
                          │                      │
                   ┌──────▼───────┐       ┌──────▼──────┐
                   │memory_server │       │   Ollama     │
                   │ .py (HTTP)   │       │ bge-small-zh │
                   │  :11435      │       └─────────────┘
                   └──────────────┘
```

| 组件 | 说明 |
|------|------|
| PostgreSQL + pgvector | 向量存储 + 全文搜索（tsvector + jieba 分词） |
| Ollama | 本地 embedding 模型（quentinz/bge-small-zh-v1.5，384维） |
| memory_system.py | CLI 工具：索引、搜索、统计 |
| memory_server.py | HTTP API 服务，端口 11435 |

**搜索策略**：向量搜索（语义） → 相似度 > 阈值直接返回 → 否则回退 BM25 全文搜索。

## 核心工作流

### 1. 存记忆

将内容写入 `memory/` 目录下的 `.md` 文件，然后执行索引：

```bash
# 写入记忆文件
# 文件名用日期或主题：memory/2025-06-11-project-decision.md

# 索引到数据库
python3 memory_system.py index
```

### 2. 查记忆

```bash
python3 memory_system.py search "搜索关键词"
```

也可通过 HTTP API：

```bash
curl "http://localhost:11435/search?q=关键词&limit=5"
```

### 3. 索引

对 `memory/` 目录下所有 `.md` 文件建立向量索引：

```bash
python3 memory_system.py index          # 增量索引（基于 hash 去重）
python3 memory_system.py index --full   # 全量重建
```

### 4. 查看统计

```bash
python3 memory_system.py stats
curl http://localhost:11435/stats
```

### 5. 图谱数据

```bash
curl http://localhost:11435/graph-data
```

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/search?q=...&limit=N` | GET | 混合搜索（向量优先，全文兜底） |
| `/index` | POST | 触发索引（增量） |
| `/stats` | GET | 记忆统计（数量、最近索引时间等） |
| `/graph-data` | GET | 图谱节点/边数据（基于内容相似度） |
| `/activity` | GET | 最近活动记录 |
| `/version` | GET | 系统版本信息 |

## 部署

### Docker Compose（推荐）

```bash
bash scripts/install.sh
```

一键安装脚本会自动：
1. 检查 Docker 环境
2. 创建 `docker-compose.yml`
3. 初始化数据库（pgvector 扩展 + 建表 + 索引）
4. 拉取 Ollama embedding 模型
5. 启动全部服务
6. 健康检查

### 手动部署

参考 `templates/` 目录下的模板文件：
- `docker-compose.yml` — 容器编排
- `systemd.service` — systemd 服务

## 配置

通过环境变量配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DB_HOST` | `localhost` | PostgreSQL 主机 |
| `DB_PORT` | `5432` | PostgreSQL 端口 |
| `DB_NAME` | `summermemory` | 数据库名 |
| `DB_USER` | `summer` | 数据库用户 |
| `DB_PASSWORD` | `summer2026` | 数据库密码 |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama 服务地址 |
| `OLLAMA_MODEL` | `quentinz/bge-small-zh-v1.5` | Embedding 模型 |
| `MEMORY_DIR` | `./memory` | 记忆文件目录 |
| `SERVER_PORT` | `11435` | HTTP API 端口 |
| `SIMILARITY_THRESHOLD` | `0.6` | 向量搜索相似度阈值 |

## ⚠️ 重要注意事项

1. **禁止直接 `read memory/*.md`**：必须通过 `search` 命令查询，确保走向量/全文搜索而非简单文件读取
2. **写入后必须索引**：写入记忆文件后执行 `index`，否则搜索不到新内容
3. **dreaming 目录**：自动索引但不应主动读取，这是系统自动生成的关联记忆
4. **路径统一**：使用相对路径（`memory/xxx`），避免绝对路径导致重复索引
5. **中文优化**：使用 jieba 分词 + BM25，中文搜索效果好于纯 tsvector
6. **幂等索引**：基于文件 hash 去重，重复索引不会产生重复记录

## OpenClaw 集成配置

### 强制使用 SummerMemory（重要）

为了让 OpenClaw **默认使用 SummerMemory 而不是内置记忆系统**，需要在 OpenClaw 配置中做两件事：

#### 1. 禁用内置记忆工具

在 `openclaw.json` 的 `tools` 配置块中添加 `deny` 列表：

```json
"tools": {
  "profile": "full",
  "deny": ["memory_search", "memory_get"],
  "exec": {
    "security": "full",
    "ask": "off",
    "host": "auto"
  }
}
```

#### 2. 注入 MEMORY.md 到每个新对话

将 `contextInjection` 设为 `"always"`，确保 MEMORY.md 的红线规则在每个新对话的系统提示中注入：

```json
"agents": {
  "defaults": {
    "contextInjection": "always"
  }
}
```

#### 为什么这样做

- **问题**：OpenClaw 自带 `memory_search` / `memory_get`，模型默认优先使用内置工具，导致不经过 SummerMemory 直接读文件
- **解决**：`deny` 从工具列表里移除这两个工具；`contextInjection` 让 MEMORY.md 的红线规则在每个新对话里都出现
- **效果**：模型第一眼就看到"用 SummerMemory"，且内置工具根本调不了，只能走 `exec + memory_system.py` 或 HTTP API

### 重启生效

修改 `openclaw.json` 后需要重启：

```bash
systemctl restart openclaw
```
