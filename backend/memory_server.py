#!/usr/bin/env python3
"""
SummerMemory v2.0 — 记忆检索服务（彻底重构版）

架构：三层漏斗 + RRF 排名融合（v2.1，对齐 Elasticsearch RRF retriever 标准）
  ① 精确直达：文件名/日期/标题直接匹配（<1ms）
  ② BM25 关键词：jieba 分词 + tsvector + 标题加权（5-20ms）
  ③ 向量语义：qwen3-embedding 0.6B Q8 1024维 + pgvector 余弦（与 BM25 并行）
  融合：RRF 排名融合 Σ 1/(k+rank)，k=60（ES 默认），双路等权，同文件取最高分 chunk

历史教训（v1 的 9 个坑，重构时全部规避）：
  - 坑1-4: 排序算法缺陷 → 三层漏斗；v2.1 用 RRF 排名融合（ES 标准）替代分数加权，不再带 Reranker
  - 坑5-6: 分块丢上下文 → 每块自带标题链 + 空标题并下文
  - 坑7:   jina 量化版排序差 → bge-m3 Q8 → v2.1 升级 qwen3-embedding 0.6B
  - 坑8:   大文件chunk累加霸榜 → 同文件只取最高分
  - 坑9:   短查询被挤掉 → v2.0 曾用「≤4字跳向量」修法；v2.1 废除门控，双路并行 + RRF 消化
"""
import json
import math
import os
import re
import threading
import time
from collections import OrderedDict
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import jieba
import numpy as np
import psycopg2
import psycopg2.extras

# ============ 配置 ============
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", 5432)),
    "dbname": os.environ.get("DB_NAME", "summer_memory"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
}
# 从环境变量文件读取密码（不硬编码）
def _load_db_password():
    global DB_CONFIG
    if DB_CONFIG["password"]:
        return
    # 优先读 systemd 环境变量，兜底读 docker-compose
    try:
        import subprocess
        r = subprocess.run(
            ["grep", "POSTGRES_PASSWORD", "/opt/middleware/docker-core/postgresql/docker-compose.yaml"],
            capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            pw = r.stdout.strip().split()[-1].strip().strip('"').strip("'")
            if pw:
                DB_CONFIG["password"] = pw
    except Exception:
        pass

_load_db_password()

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-embedding:0.6b-q8_0")  # v2.1: bge-m3:q8 保留在 ollama，随时可切回
VECTOR_DIM = 1024

WORKSPACE = Path("/root/.openclaw/workspace")
PORT = 11435

# 分块参数
MAX_CHUNK_CHARS = 800
MIN_MERGE_CHARS = 50

# 融合权重（v2.0 调优：BM25 是主力，向量是语义补充）
# v2.1: RRF 排名融合，不再使用固定权重（W_VECTOR/W_BM25 已废弃删除）

# 查询缓存（LRU 200 条，命中直接返回，0ms）
_QUERY_CACHE = OrderedDict()
_QUERY_CACHE_LOCK = threading.Lock()
CACHE_MAX = 200


def cache_get(key):
    with _QUERY_CACHE_LOCK:
        if key in _QUERY_CACHE:
            _QUERY_CACHE.move_to_end(key)
            return _QUERY_CACHE[key]
    return None


def cache_put(key, value):
    with _QUERY_CACHE_LOCK:
        _QUERY_CACHE[key] = value
        if len(_QUERY_CACHE) > CACHE_MAX:
            _QUERY_CACHE.popitem(last=False)


def cache_clear():
    """消空查询缓存（索引更新后调用，防止旧结果滞留）"""
    with _QUERY_CACHE_LOCK:
        _QUERY_CACHE.clear()


# ============ 分块（v2.0 重做） ============
def chunk_markdown(text: str, file_title: str = "") -> List[Dict[str, Any]]:
    """
    v2.0 分块策略：
    1. 按 ## / ### 标题切分，空标题节并入**下文**（v1 是并入上文，坑6）
    2. 每个 chunk 自带标题链上下文："文件名 > 章节标题"（坑5：防止上下文丢失）
    返回 [{content, heading}]，heading 用于 BM25 标题加权
    """
    header_pattern = re.compile(r'^(#{2,}\s.+)$', re.MULTILINE)

    # 解析成 (标题, 正文) 段落列表
    sections = []
    current_heading = ""
    last_end = 0
    for m in header_pattern.finditer(text):
        seg = text[last_end:m.start()].strip()
        if seg:
            sections.append((current_heading, seg))
        current_heading = m.group(1).strip()
        last_end = m.start()
    tail = text[last_end:].strip()
    if tail:
        sections.append((current_heading, tail))

    # 无标题 → 整篇一段
    if not sections:
        stripped = text.strip()
        if not stripped:
            return []
        sections = [("", stripped)]

    # 空正文标题并入下文（v1 坑6：并入上文导致"待办"和内容分离）
    merged_sections = []
    pending_heading = ""
    for heading, body in sections:
        if len(body) < MIN_MERGE_CHARS and not merged_sections or (len(body) < 20 and heading):
            # 正文太短的标题节：标题挂起，正文并入下一节
            pending_heading = (pending_heading + " " + heading).strip() if pending_heading else heading
            # 但如果 body 非空还是保留它
            if body:
                merged_sections.append((pending_heading, body))
                pending_heading = ""
        else:
            if pending_heading:
                heading = (pending_heading + " " + heading).strip()
                pending_heading = ""
            merged_sections.append((heading, body))
    if pending_heading and merged_sections:
        # 末尾挂起的标题并入最后节
        merged_sections[-1] = (merged_sections[-1][0] + " " + pending_heading, merged_sections[-1][1])

    # 长段切分（按空行，超长硬切）
    chunks = []
    for heading, body in merged_sections:
        pieces = [body] if len(body) <= MAX_CHUNK_CHARS else _split_long(body)
        for piece in pieces:
            chunks.append({"heading": heading, "content": piece})

    # 过滤空块
    return [c for c in chunks if c["content"].strip()]


def _split_long(body: str) -> List[str]:
    """超长正文按空行拆，仍超长按 max_chars 硬切"""
    parts = []
    current = ""
    for sp in re.split(r'\n\s*\n', body):
        sp = sp.strip()
        if not sp:
            continue
        if len(current) + len(sp) + 2 <= MAX_CHUNK_CHARS:
            current = (current + "\n\n" + sp) if current else sp
        else:
            if current:
                parts.append(current)
            if len(sp) > MAX_CHUNK_CHARS:
                for i in range(0, len(sp), MAX_CHUNK_CHARS):
                    parts.append(sp[i:i + MAX_CHUNK_CHARS])
            else:
                current = sp
                continue
            current = ""
    if current:
        parts.append(current)
    return parts


def build_chunk_text(chunk: Dict[str, Any], file_title: str) -> str:
    """构建带标题链的 chunk 文本（供 embedding 和 BM25 用）"""
    heading = chunk["heading"].lstrip("# ").strip()
    if heading:
        return f"[{file_title} > {heading}]\n{chunk['content']}"
    return f"[{file_title}]\n{chunk['content']}"


# ============ Ollama 调用 ============
def get_embedding(text: str) -> Optional[List[float]]:
    """单条转向量"""
    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            data=json.dumps({"model": OLLAMA_MODEL, "prompt": text}).encode(),
            headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read()).get("embedding")
        return result if result else None
    except Exception as e:
        print(f"[embedding] 失败: {e}")
        return None


def get_embeddings_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """批量转向量（索引时用，快 3-5 倍）"""
    if not texts:
        return []
    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/embed",
            data=json.dumps({"model": OLLAMA_MODEL, "input": texts}).encode(),
            headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=120)
        embeddings = json.loads(resp.read()).get("embeddings", [])
        return [e if e else None for e in embeddings]
    except Exception:
        # 逐条兜底
        return [get_embedding(t) for t in texts]


# ============ 核心系统 ============
class MemorySystem:
    def __init__(self):
        self.conn = None
        self._ensure_connection()
        self._ensure_tables()
        self._ensure_graph_cache_table()

    def _ensure_connection(self):
        if self.conn and not self.conn.closed:
            try:
                self.conn.execute("SELECT 1" if False else "SELECT 1")
                return
            except Exception:
                pass
        self.conn = psycopg2.connect(**DB_CONFIG)
        self.conn.autocommit = False

    def _ensure_tables(self):
        """建表（v2.0 结构：加 heading 列用于标题加权）"""
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id SERIAL PRIMARY KEY,
                    path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    heading TEXT DEFAULT '',
                    embedding vector(1024),
                    content_tsv TSVECTOR,
                    metadata JSONB DEFAULT '{}',
                    hash TEXT,
                    chunk_index INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS memories_path_idx ON memories(path);
                CREATE INDEX IF NOT EXISTS memories_embedding_idx
                    ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
            """)
            # 旧表升级：若无 heading 列则加
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='memories' AND column_name='heading'
            """)
            if not cur.fetchone():
                cur.execute("ALTER TABLE memories ADD COLUMN heading TEXT DEFAULT ''")
            # 维度检查：若旧表是 512/768 维需迁移
            cur.execute("""
                SELECT format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute a
                WHERE a.attrelid='memories'::regclass AND a.attname='embedding'
            """)
            row = cur.fetchone()
            if row and '1024' not in row[0]:
                # 旧维度向量全部失效，清空待重建（表结构改为 1024）
                cur.execute("UPDATE memories SET embedding = NULL")
                cur.execute("ALTER TABLE memories ALTER COLUMN embedding TYPE vector(1024)")
        self.conn.commit()

    # ---------- 图谱质心缓存表（内存开销0，DB管理）----------
    def _ensure_graph_cache_table(self):
        """质心缓存表：path 主键 + 1024维质心 + 元信息。graph-data 直接查这张表"""
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS graph_centroids (
                    path TEXT PRIMARY KEY,
                    centroid vector(1024),
                    chunks INTEGER,
                    size INTEGER,
                    updated_at TIMESTAMP
                )
            """)
        self.conn.commit()

    def _refresh_graph_centroid(self, path: str):
        """增量刷新单文件质心（index 时调用）"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT count(*), coalesce(max((metadata->>'size')::int), 0),
                           max(metadata->>'mtime'), avg(embedding)::text
                    FROM memories WHERE path=%s AND embedding IS NOT NULL
                """, (path,))
                row = cur.fetchone()
                if not row or not row[0] or not row[3]:
                    cur.execute("DELETE FROM graph_centroids WHERE path=%s", (path,))
                    return
                chunks, size, mtime_str, cent_str = row
                updated = datetime.fromisoformat(mtime_str) if mtime_str else None
                vec = json.loads(cent_str)
                # 归一化质心
                n = math.sqrt(sum(x*x for x in vec)) or 1.0
                vec = [x/n for x in vec]
                cent_pg = "[" + ",".join(str(x) for x in vec) + "]"
                cur.execute("""
                    INSERT INTO graph_centroids (path, centroid, chunks, size, updated_at)
                    VALUES (%s, %s::vector, %s, %s, %s)
                    ON CONFLICT (path) DO UPDATE SET
                        centroid=EXCLUDED.centroid, chunks=EXCLUDED.chunks,
                        size=EXCLUDED.size, updated_at=EXCLUDED.updated_at
                """, (path, cent_pg, chunks, size or chunks*800, updated))
        except Exception as e:
            print(f"[GraphCache] 刷新 {path} 失败: {e}")

    def rebuild_all_centroids(self):
        """全量重建质心（初始化或大批量变更后）"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT path FROM memories WHERE embedding IS NOT NULL")
            paths = [r[0] for r in cur.fetchall()]
        for p in paths:
            self._refresh_graph_centroid(p)
        self.conn.commit()

    def get_graph_data(self, threshold: float = 0.85) -> Dict[str, Any]:
        """图谱数据：质心表直查（DB聚合，内存0开销），nodes按path字母序（对齐旧版）"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT path, chunks, size, updated_at, centroid::text
                FROM graph_centroids ORDER BY path
            """)
            rows = cur.fetchall()
        nodes, vecs = [], {}
        for path, chunks, size, updated, cent in rows:
            try:
                v = json.loads(cent)
                vecs[path] = v
            except Exception:
                continue
            updated_str = updated.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(updated, "strftime") else str(updated)
            nodes.append({
                "id": path, "name": Path(path).name, "type": "file",
                "val": max(1, min(10, size / 1000)),
                "group": Path(path).parent.name or "root",
                "path": path, "size": size, "chunks": chunks,
                "fileSize": size, "label": Path(path).name,
                "last_updated": updated_str,
            })
        # O(n^2) 链接 —— numpy 矩阵化（176文件 <10ms）
        links = []
        paths = sorted(vecs.keys())
        if paths:
            M = np.array([vecs[p] for p in paths])          # (n, 1024)
            S = M @ M.T                                       # 全量余弦矩阵
            iu = np.triu_indices(len(paths), k=1)              # 上三角对
            sims = S[iu]
            mask = sims > threshold
            for (i, j), sim in zip(zip(iu[0][mask], iu[1][mask]), sims[mask]):
                links.append({"source": paths[i], "target": paths[j], "weight": float(sim)})
        return {"nodes": nodes, "links": links}

    # ---------- 索引 ----------
    def index_workspace(self) -> Dict[str, Any]:
        """全量/增量索引 memory 目录"""
        results = {"indexed": 0, "updated": 0, "unchanged": 0, "failed": 0, "details": []}
        memory_dir = WORKSPACE / "memory"
        if not memory_dir.exists():
            return results

        extensions = {'.md', '.json', '.yaml', '.yml', '.txt'}
        for f in sorted(memory_dir.rglob('*')):
            if not (f.is_file() and f.suffix in extensions):
                continue
            f_str = str(f)
            if '.dreams' in f_str or 'node_modules' in f_str or 'dreaming' in f_str:
                continue
            # 代码级排除 OpenClaw session-memory hook 的会话快照（YYYY-MM-DD-HHMM.md）：
            # 该 hook 在 /new /reset 时自动 dump 最后15条对话，属于官方机制继续保留文件本身，
            # 但完整对话已在 conversations 表，快照不进搜索索引/图谱（2026-08-26 主人指示）
            import re as _re_idx
            if _re_idx.match(r'\d{4}-\d{2}-\d{2}-\d{4}\.md$', f.name):
                continue

            try:
                result = self._index_file(f, memory_dir)
                results[result["status"]] = results.get(result["status"], 0) + 1
                # unchanged 只计数不进 details（避免输出刷屏）；变更/失败才记录明细
                if result["status"] != "unchanged":
                    results["details"].append(result)
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"path": str(f), "status": "failed", "error": str(e)})

        # 清理孤儿 chunks（源文件已删除的记忆，索引同步删除）
        with self.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT path FROM memories")
            db_paths = [r[0] for r in cur.fetchall()]
            removed = []
            for rel in db_paths:
                abs_path = WORKSPACE / rel
                if not abs_path.exists():
                    cur.execute("DELETE FROM memories WHERE path=%s", (rel,))
                    removed.append(rel)
            if removed:
                print(f"[index] 清理 {len(removed)} 个已删除文件的孤儿chunks")
                results["removed"] = len(removed)

        self.conn.commit()
        # 索引变更后清空查询缓存（v2.1 修复：防止搜到旧结果，TODO.md 事件发现）
        if results.get("updated") or results.get("indexed") or results.get("removed"):
            cache_clear()
        # 增量刷新变更文件的图谱质心
        for d in results["details"]:
            if d.get("status") in ("updated", "indexed"):
                self._refresh_graph_centroid(d["path"])
        self.conn.commit()
        return results

    def _file_hash(self, path: Path) -> str:
        import hashlib
        h = hashlib.md5()
        h.update(path.read_bytes())
        return h.hexdigest()

    def _index_file(self, f: Path, memory_dir: Path) -> Dict[str, Any]:
        rel_path = "memory/" + str(f.relative_to(memory_dir))
        file_title = f.stem  # 文件名（不带扩展名）作为标题
        content = f.read_text(encoding="utf-8", errors="replace")
        new_hash = self._file_hash(f)

        with self.conn.cursor() as cur:
            # hash 对比：没变就跳过（增量）
            cur.execute("SELECT DISTINCT hash FROM memories WHERE path=%s LIMIT 1", (rel_path,))
            row = cur.fetchone()
            if row and row[0] == new_hash:
                # 检查是否有空 embedding 需要补
                cur.execute("SELECT count(*) FROM memories WHERE path=%s AND embedding IS NULL", (rel_path,))
                if cur.fetchone()[0] == 0:
                    return {"path": rel_path, "status": "unchanged", "chunks": 0}

            # 删旧 chunks
            cur.execute("DELETE FROM memories WHERE path=%s", (rel_path,))

        # 分块（v2.0：带标题链）
        chunks = chunk_markdown(content, file_title)
        if not chunks:
            return {"path": rel_path, "status": "empty", "chunks": 0}

        # 批量 embedding
        texts = [build_chunk_text(c, file_title) for c in chunks]
        embeddings = get_embeddings_batch(texts)

        # 分词函数
        def tok(t):
            return " ".join(jieba.cut_for_search(t))

        with self.conn.cursor() as cur:
            for i, chunk in enumerate(chunks):
                text = texts[i]
                emb = embeddings[i]
                # emb 转 pgvector 字符串
                emb_str = "[" + ",".join(str(x) for x in emb) + "]" if emb else None
                mtime_iso = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                cur.execute("""
                    INSERT INTO memories (path, content, heading, embedding, content_tsv, metadata, hash, chunk_index)
                    VALUES (%s, %s, %s, %s::vector, to_tsvector('simple', %s), %s::jsonb, %s, %s)
                """, (rel_path, chunk["content"], chunk["heading"], emb_str,
                      tok(text), json.dumps({"size": len(content), "mtime": mtime_iso}), new_hash, i))

        return {"path": rel_path, "status": "updated", "chunks": len(chunks)}

    # ---------- 搜索：三层漏斗 ----------
    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        v2.0 三层漏斗搜索
        ① 精确直达：路径/文件名/日期完全匹配
        ② BM25：jieba 分词 + OR 检索 + 标题命中加权
        ③ 向量：bge-m3 语义检索
        融合：0.55/0.45 加权，同文件取最高分 chunk
        """
        self._ensure_connection()
        query = query.strip()
        if not query:
            return []

        # 缓存命中直接返回（0ms）
        cache_key = f"{query}:{limit}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

        tokens = [t for t in jieba.cut_for_search(query) if t.strip()]

        # ---- ① 精确直达（文件名/日期）----
        exact = self._exact_match(query, limit)
        exact_paths = {r["path"] for r in exact}

        # ---- ② BM25 与 ③ 向量化并行执行（总耗时 = 较慢者，而非相加）----
        # v2.1: 删除短查询门控（原坑9修法）——ES/Qdrant 无此规则，短词语义召回交给 RRF 融合消化
        vec_holder = {}

        def _vec_worker():
            emb = get_embedding(query)
            if emb:
                emb_str = "[" + ",".join(str(x) for x in emb) + "]"
                vec_holder["emb_str"] = emb_str

        t_vec = threading.Thread(target=_vec_worker)
        t_vec.start()
        bm25_results = self._bm25_search(query, tokens, limit * 5)
        t_vec.join(timeout=30)

        # 向量检索（与 BM25 并行完成嵌入后）
        vec_results = []
        if "emb_str" in vec_holder:
            vec_results = self._vector_search(vec_holder["emb_str"], limit * 5)

        # ---- 融合 ----
        result = self._fuse(exact, bm25_results, vec_results, exact_paths, limit)
        cache_put(cache_key, result)
        return result

    def _exact_match(self, query: str, limit: int) -> List[Dict]:
        """精确直达：仅路径/文件名/日期命中（v2.1 方案A：去掉 heading 匹配，
        标题命中交给 BM25 的 ×2 加权和 RRF 公平竞争，防止 exact 无上限置顶挤掉正文召回）"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (path) path, content, heading, chunk_index
                    FROM memories
                    WHERE path ILIKE %s
                    LIMIT %s
                """, (f"%{query}%", limit))
                return [{"path": r[0], "content": r[1], "heading": r[2],
                         "chunk_index": r[3], "exact": True} for r in cur.fetchall()]
        except Exception:
            return []

    def _bm25_search(self, query: str, tokens: List[str], limit: int) -> List[Dict]:
        """BM25 + 标题加权（命中 heading 的结果分数×2）"""
        if not tokens:
            return []
        # OR 逻辑（AND 在自然语言查询上召回太差，v1 坑）
        tsq = " | ".join(self._escape_tsquery_token(t) for t in tokens if len(t.strip()) > 0)
        if not tsq:
            return []
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT path, content, heading, chunk_index,
                           ts_rank(content_tsv, to_tsquery('simple', %s)) AS rank
                    FROM memories
                    WHERE content_tsv @@ to_tsquery('simple', %s)
                    ORDER BY rank DESC
                    LIMIT %s
                """, (tsq, tsq, limit))
                results = []
                for r in cur.fetchall():
                    score = float(r[4])
                    # 标题命中加权（v2.0 新增）
                    if r[2] and any(t in r[2] for t in tokens if len(t) > 1):
                        score *= 2.0
                    # 文件名命中加权
                    if any(t in r[0] for t in tokens if len(t) > 1):
                        score *= 1.5
                    results.append({"path": r[0], "content": r[1], "heading": r[2],
                                    "chunk_index": r[3], "bm25_score": score})
                return results
        except Exception as e:
            print(f"[bm25] {e}")
            return []

    @staticmethod
    def _escape_tsquery_token(token: str) -> str:
        """转义 tsquery 特殊字符"""
        return re.sub(r"[&|!()<>:'\\]", " ", token).strip() or "无"

    def _vector_search(self, emb_str: str, limit: int) -> List[Dict]:
        """pgvector 余弦相似度检索"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT path, content, heading, chunk_index,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM memories
                    WHERE embedding IS NOT NULL
                    ORDER BY similarity DESC
                    LIMIT %s
                """, (emb_str, limit))
                return [{"path": r[0], "content": r[1], "heading": r[2],
                         "chunk_index": r[3], "vec_score": float(r[4])} for r in cur.fetchall()]
        except Exception as e:
            print(f"[vector] {e}")
            return []

    def _fuse(self, exact, bm25_results, vec_results, exact_paths, limit) -> List[Dict]:
        """
        v2.1 RRF 排名融合（对齐 Elasticsearch RRF retriever 默认形态）
        score(d) = Σ 1/(k + rank)，k=60（ES rank_constant 默认），rank 1-based
        - 双路等权，文档双路命中则贡献累加（ES 公式：score += 1/(k+rank)）
        - 同文件每路只取最优块再参与（坑8 防霸榜，等价 ES collapse）
        - 一路未召回不拖累另一路（治：BM25 零分稀释向量语义召回）
        - 精确直达置顶不参与 RRF 竞争（记忆系统刚需，自家扩展层）
        """
        K = 60  # ES rank_constant 默认值，业界共识

        def best_per_file(results):
            """结果已按本路降序，同文件取首个出现的块 = 该路最优块"""
            best = {}
            for pos, r in enumerate(results, start=1):
                if r["path"] not in best:
                    best[r["path"]] = (pos, r)  # (该路排名, 块数据)
            return best

        vec_best = best_per_file(vec_results)     # path -> (向量路排名, chunk)
        bm25_best = best_per_file(bm25_results)   # path -> (BM25路排名, chunk)

        scores, items = {}, {}  # path -> rrf总分, path -> 展示块

        def accumulate(best):
            """把某一路的排名转成 RRF 贡献并累加"""
            for p, (rank, item) in best.items():
                c = 1.0 / (K + rank)  # 该路 RRF 贡献：排名越靠前贡献越大
                scores[p] = scores.get(p, 0.0) + c
                # 展示块 = 贡献更大的那路的块（两路都命中时取更优路的）
                if p not in items or c > items[p]["_contrib"]:
                    items[p] = {**item, "_contrib": c}

        accumulate(vec_best)
        accumulate(bm25_best)

        # 按 RRF 总分降序
        ranked = sorted(scores, key=lambda p: scores[p], reverse=True)

        # 精确匹配的置顶（保持 v2.0 行为不变）
        final = []
        for e in exact:
            final.append({
                "path": e["path"], "content": e["content"], "heading": e.get("heading", ""),
                "chunk_index": e.get("chunk_index", 0),
                "similarity": 1.0, "matched_by": "exact",
            })
        for p in ranked:
            if p in exact_paths:
                continue
            if len(final) >= limit:
                break
            it = items[p]
            in_vec, in_bm = p in vec_best, p in bm25_best
            matched = "vector+bm25" if (in_vec and in_bm) else ("vector" if in_vec else "bm25")
            final.append({
                "path": p, "content": it["content"], "heading": it.get("heading", ""),
                "chunk_index": it.get("chunk_index", 0),
                "similarity": round(scores[p], 6),
                "matched_by": matched,
            })
        return final[:limit]

    def get_timeline(self) -> Dict[str, Any]:
        """时间轴：按文件真实修改时间(mtime)聚合，graph 前端用"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT substring(metadata->>'mtime' from 1 for 10) AS date,
                       count(DISTINCT path) AS files
                FROM memories
                WHERE metadata->>'mtime' IS NOT NULL
                GROUP BY 1 ORDER BY 1 DESC LIMIT 90
            """)
            timeline = [{"date": r[0], "files": r[1]} for r in cur.fetchall()]
        return {"timeline": timeline}

    # ---------- 统计 ----------
    def stats(self) -> Dict:
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(DISTINCT path), count(*) FROM memories")
            files, chunks = cur.fetchone()
            cur.execute("SELECT max(updated_at) FROM memories")
            last = cur.fetchone()[0]
        return {"total_files": files, "total_chunks": chunks, "last_updated": str(last),
                "engine": OLLAMA_MODEL, "vector_dim": VECTOR_DIM}


# ============ HTTP 服务 ============
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse as urlparse


class Handler(BaseHTTPRequestHandler):
    system: MemorySystem = None

    def log_message(self, fmt, *args):
        pass  # 静默访问日志

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse.urlparse(self.path)
        params = {k: v[0] for k, v in urlparse.parse_qs(parsed.query).items()}

        try:
            if parsed.path == "/health":
                self._json({"status": "ok", "engine": OLLAMA_MODEL})
            elif parsed.path == "/index":
                # 手动重建索引（CLI: memory_system index 调用）
                # 2026-08-26 v2.0 重构时误删，现补回；长任务给足超时
                result = self.system.index_workspace()
                self._json(result)
            elif parsed.path == "/search":
                q = params.get("query", "")
                limit = int(params.get("limit", 10))
                result = self.system.search(q, limit)
                self._json(result)
                # 广播检索事件（graph 前端检索动画）
                _broadcast_activity("search", query=q)
            elif parsed.path == "/stats":
                self._json(self.system.stats())
            elif parsed.path == "/graph-data":
                threshold = float(params.get("threshold", 0.85))
                self._json(self.system.get_graph_data(threshold))
            elif parsed.path == "/version":
                # 返回数据版本时间戳（memories 最大 updated_at 的 epoch）
                # 前端轮询此值，变化时提示用户刷新（旧版行为，必须保留）
                try:
                    self.system._ensure_connection()
                    with self.system.conn.cursor() as cur:
                        cur.execute("SELECT EXTRACT(EPOCH FROM MAX(updated_at))::bigint FROM memories")
                        row = cur.fetchone()
                        ver = int(row[0]) if row and row[0] else 0
                except Exception:
                    ver = 0
                self._json({"version": ver})
            elif parsed.path == "/timeline":
                self._json(self.system.get_timeline())
            elif parsed.path == "/conv/list":
                self._json(self._conv_list(params.get("q")))
            elif parsed.path == "/conv/get":
                self._json(self._conv_get(params.get("key", "")))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ---- 对话归档（读取 v1 遗留的 conversations 表，功能不变）----
    def _conv_list(self, keyword):
        with self.system.conn.cursor() as cur:
            if keyword:
                cur.execute("""
                    SELECT DISTINCT session_key, min(timestamp), count(*),
                           (array_agg(content::text ORDER BY timestamp))[1]
                    FROM conversations
                    WHERE content::text ILIKE %s
                    GROUP BY session_key ORDER BY 2 DESC LIMIT 50
                """, (f"%{keyword}%",))
            else:
                cur.execute("""
                    SELECT DISTINCT session_key, min(timestamp), count(*),
                           (array_agg(content::text ORDER BY timestamp))[1]
                    FROM conversations
                    GROUP BY session_key ORDER BY 2 DESC LIMIT 50
                """)
            return [{"session_key": r[0], "started": str(r[1]), "messages": r[2],
                     "preview": (r[3] or "")[:100]} for r in cur.fetchall()]

    def _conv_get(self, key):
        """获取完整会话，支持 session_key 或 sessionId UUID（dashboard key 兼容）"""
        with self.system.conn.cursor() as cur:
            # 优先精确匹配 session_key
            cur.execute("""
                SELECT role, timestamp, content::text
                FROM conversations
                WHERE session_key = %s ORDER BY timestamp, id
            """, (key,))
            rows = cur.fetchall()
            # 精确没命中，尝试按 sessionId 模糊匹配（支持 dashboard key 场景）
            if not rows and '-' in key:
                cur.execute("""
                    SELECT role, timestamp, content::text
                    FROM conversations
                    WHERE session_key LIKE %s ORDER BY timestamp, id
                """, (f"%{key}%",))
                rows = cur.fetchall()
            return [{"role": r[0], "timestamp": str(r[1]), "content": r[2][:2000]} for r in rows]


# ---- WebSocket 广播管理（从 v1 移植，graph 前端检索动画/在线人数依赖此服务）----
import asyncio
import threading
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

WS_PORT = 8890  # graphWs 隧道端口（nginx /graphWs → frpc → 本机 8890）


class WebSocketManager:
    """管理所有 WebSocket 客户端连接，并提供线程安全的广播方法"""

    def __init__(self):
        self._clients = set()
        self._loop = None  # WS 服务的 asyncio 事件循环（跨线程广播用）

    def set_loop(self, loop):
        self._loop = loop

    def register(self, ws):
        self._clients.add(ws)

    def unregister(self, ws):
        self._clients.discard(ws)

    @property
    def count(self):
        return len(self._clients)

    def broadcast_online_count(self):
        """广播当前在线人数（连接/断开时触发）"""
        self.broadcast({"type": "online_count", "count": self.count})

    def broadcast(self, message: dict):
        """线程安全地向所有 WS 客户端广播 JSON 消息（从任意线程调用）"""
        if not self._clients or not self._loop or not self._loop.is_running():
            return
        data = json.dumps(message, ensure_ascii=False)
        for ws in list(self._clients):
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future, self._safe_send(ws, data))

    @staticmethod
    async def _safe_send(ws, data: str):
        try:
            await ws.send(data)
        except Exception:
            pass


ws_manager = WebSocketManager()


async def _ws_handler(websocket):
    """单个 WS 连接的生命周期管理"""
    ws_manager.register(websocket)
    ws_manager.broadcast_online_count()
    try:
        async for _ in websocket:
            pass  # 保持连接，等待客户端断开
    except Exception:
        pass
    finally:
        ws_manager.unregister(websocket)
        ws_manager.broadcast_online_count()


def _run_ws_server():
    """在独立线程中运行 WS 服务（8890），供 graph 前端实时事件"""
    if not HAS_WEBSOCKETS:
        print("[WS] websockets 库未安装，跳过 WebSocket 服务")
        return
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ws_manager.set_loop(loop)

    async def start():
        # 新版 websockets 库不再接受 loop 参数；serve 在当前 loop 上运行
        return await websockets.serve(_ws_handler, "0.0.0.0", WS_PORT)

    try:
        server = loop.run_until_complete(start())
        print(f"[WS] WebSocket 服务运行在端口 {WS_PORT}")
        loop.run_forever()
    except Exception as e:
        print(f"[WS] 启动失败: {e}")


def _broadcast_activity(action: str, path: str = "", query: str = ""):
    """广播 activity 事件（检索动画数据源），失败不影响主流程"""
    try:
        ws_manager.broadcast({
            "type": "activity",
            "action": action,
            "path": path,
            "query": query,
        })
    except Exception:
        pass


def main():
    print("[SummerMemory v2.0] 启动中...")
    Handler.system = MemorySystem()
    # WebSocket 服务线程（graph 前端检索动画/在线人数）
    ws_thread = threading.Thread(target=_run_ws_server, daemon=True)
    ws_thread.start()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[SummerMemory v2.0] 端口 {PORT} 就绪，引擎 {OLLAMA_MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
