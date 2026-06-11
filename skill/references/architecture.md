# SummerMemory 系统架构

## 概述

SummerMemory 是一个自建 AI 记忆系统，采用混合搜索策略（向量语义搜索 + BM25 全文搜索），针对中文场景优化，支持知识图谱可视化。

## 组件架构

```
                    ┌──────────────────┐
                    │    用户 / CLI     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  memory_server.py │  HTTP API :11435
                    │  memory_system.py │  CLI 工具
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐
     │  PostgreSQL    │ │  Ollama  │ │  memory/    │
     │  + pgvector    │ │  :11434  │ │  (*.md)     │
     │  + tsvector    │ │          │ │             │
     │  + jieba 分词  │ │ bge-small│ │ 记忆文件源  │
     └───────────────┘ └──────────┘ └─────────────┘
```

## 数据流

### 索引流程

1. 扫描 `memory/` 目录下所有 `.md` 文件
2. 计算文件内容 hash，与数据库比对（增量索引）
3. 新增/变更文件：
   - jieba 分词 → 生成 tsvector（全文搜索）
   - Ollama embedding → 生成 384 维向量（语义搜索）
4. 写入 PostgreSQL（upsert by path）

### 搜索流程

1. 用户输入查询关键词
2. **向量搜索**：查询文本 → Ollama embedding → pgvector cosine search
3. 若最高相似度 > 阈值（默认 0.6）→ 直接返回向量搜索结果
4. 否则回退 **BM25 全文搜索**：jieba 分词 → tsvector 匹配
5. 返回结果（含 search_type 标记）

## 数据库设计

### memories 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| path | TEXT | 记忆文件相对路径（唯一） |
| content | TEXT | 文件内容 |
| embedding | vector(384) | Ollama 生成的向量 |
| content_tsv | tsvector | jieba 分词后的全文搜索向量 |
| metadata | JSONB | 扩展元数据 |
| hash | TEXT | 文件内容 hash（用于增量索引） |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

### memory_activity 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| action | TEXT | 操作类型（index/search） |
| path | TEXT | 相关文件路径 |
| query | TEXT | 搜索查询 |
| timestamp | TIMESTAMP | 操作时间 |

## 图谱生成

`/graph-data` 接口基于以下规则生成图谱：
- **节点**：每个记忆文件为一个节点
- **边**：基于向量余弦相似度，超过阈值的文件对生成边
- **权重**：相似度分数作为边权重
- **聚类**：路径相似度（同目录）增加额外连接权重

## Dreaming 系统

三层梦境自动生成关联记忆：
- **deep dream**：深度关联，跨领域连接
- **light dream**：轻度关联，同主题延伸
- **rem dream**：随机探索，意外发现

Dreaming 生成的记忆存放在 `dreaming/` 目录，会被自动索引但不应主动读取。

## 技术选型

| 技术 | 用途 | 原因 |
|------|------|------|
| PostgreSQL + pgvector | 向量存储 + 搜索 | 成熟、支持混合查询 |
| Ollama + bge-small-zh-v1.5 | 中文 embedding | 本地部署、中文优化、384维轻量 |
| jieba | 中文分词 | 中文分词效果最好的开源方案 |
| tsvector + GIN | 全文搜索 | PostgreSQL 原生支持、配合 BM25 |
| ivfflat 索引 | 向量近似搜索 | pgvector 原生索引、适合中等规模数据 |
