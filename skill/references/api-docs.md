# SummerMemory API 文档

基础地址：`http://localhost:11435`

## 搜索

```
GET /search?q=<关键词>&limit=<数量>
```

**搜索策略**：向量搜索优先（语义相似度），低于阈值时回退 BM25 全文搜索。

**参数**：
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `q` | string | 必填 | 搜索关键词 |
| `limit` | int | 10 | 返回结果数量 |

**响应**：
```json
{
  "results": [
    {
      "id": 1,
      "path": "memory/2025-06-11-decision.md",
      "content": "记忆内容摘要...",
      "score": 0.87,
      "search_type": "vector"
    }
  ],
  "query": "关键词",
  "total": 1,
  "search_type": "vector"
}
```

`search_type` 值：`vector`（向量搜索命中）或 `fulltext`（全文搜索兜底）。

## 索引

```
POST /index
```

触发增量索引。扫描 `MEMORY_DIR` 下所有 `.md` 文件，基于 hash 去重后生成 embedding 并写入数据库。

**响应**：
```json
{
  "indexed": 5,
  "skipped": 12,
  "errors": 0,
  "duration_ms": 3200
}
```

## 统计

```
GET /stats
```

**响应**：
```json
{
  "total_memories": 42,
  "last_indexed": "2025-06-11T10:30:00Z",
  "db_size_mb": 15.3,
  "index_status": "ready"
}
```

## 图谱数据

```
GET /graph-data
```

基于文件内容相似度和路径关系生成节点/边数据，用于 Cosmograph 等图谱可视化。

**响应**：
```json
{
  "nodes": [
    { "id": 1, "label": "project-decision", "path": "memory/2025-06-11-decision.md", "size": 3 }
  ],
  "edges": [
    { "source": 1, "target": 2, "weight": 0.85 }
  ]
}
```

## 活动记录

```
GET /activity?limit=<数量>
```

**参数**：
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `limit` | int | 20 | 返回记录数量 |

**响应**：
```json
{
  "activities": [
    {
      "id": 1,
      "action": "index",
      "path": null,
      "query": null,
      "timestamp": "2025-06-11T10:30:00Z"
    }
  ]
}
```

## 版本

```
GET /version
```

**响应**：
```json
{
  "version": "1.0.0",
  "model": "quentinz/bge-small-zh-v1.5",
  "embedding_dim": 384
}
```
