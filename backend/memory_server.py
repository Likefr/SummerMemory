#!/usr/bin/env python3
"""
SummerMemory v2.0 — 记忆检索服务（彻底重构版）

架构：三层漏斗 + 分数融合
  ① 精确直达：文件名/日期/标题直接匹配（<1ms）
  ② BM25 关键词：jieba 分词 + tsvector + 标题加权（5-20ms）
  ③ 向量语义：bge-m3 Q8 1024维 + pgvector 余弦（~230ms）
  融合：向量×0.55 + BM25×0.45，同文件只取最高分 chunk

历史教训（v1 的 9 个坑，重构时全部规避）：
  - 坑1-4: 排序算法缺陷 → 三层漏斗 + 分数融合替代 RRF/重排
  - 坑5-6: 分块丢上下文 → 每块自带标题链 + 空标题并下文
  - 坑7:   jina 量化版排序差 → bge-m3 Q8
  - 坑8:   大文件chunk累加霸榜 → 同文件只取最高分
  - 坑9:   短查询被挤掉 → 默认limit 10 + 短查询纯BM25
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
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "bge-m3:q8")
VECTOR_DIM = 1024

WORKSPACE = Path("/root/.openclaw/workspace")
PORT = 11435

# 分块参数
MAX_CHUNK_CHARS = 800
MIN_MERGE_CHARS = 50

# 融合权重（v2.0 调优：BM25 是主力，向量是语义补充）
W_VECTOR = 0.55
W_BM25 = 0.45

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
            try:
                result = self._index_file(f, memory_dir)
                results[result["status"]] = results.get(result["status"], 0) + 1
                results["details"].append(result)
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"path": str(f), "status": "failed", "error": str(e)})

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
                cur.execute("""
                    INSERT INTO memories (path, content, heading, embedding, content_tsv, metadata, hash, chunk_index)
                    VALUES (%s, %s, %s, %s::vector, to_tsvector('simple', %s), %s::jsonb, %s, %s)
                """, (rel_path, chunk["content"], chunk["heading"], emb_str,
                      tok(text), json.dumps({"size": len(content)}), new_hash, i))

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
        use_vector = len(query) > 4  # >4 字才走向量（坑9）
        vec_holder = {}

        def _vec_worker():
            if use_vector:
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
        """精确直达：路径含查询词（如日期、文件名）"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (path) path, content, heading, chunk_index
                    FROM memories
                    WHERE path ILIKE %s OR heading ILIKE %s
                    LIMIT %s
                """, (f"%{query}%", f"%{query}%", limit))
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
        """分数融合：向量0.55 + BM25 0.45，同文件只取最高分（坑8），精确直达置顶"""
        vec_max = max((r["vec_score"] for r in vec_results), default=0) or 1.0
        bm25_max = max((r["bm25_score"] for r in bm25_results), default=0) or 1.0

        merged = {}  # path -> best

        def offer(item, score):
            p = item["path"]
            if p not in merged or score > merged[p]["score"]:
                merged[p] = {**item, "score": score}

        # 向量命中
        for r in vec_results:
            nv = r["vec_score"] / vec_max
            nb = (r.get("bm25_score", 0) / bm25_max) if r.get("bm25_score") else 0
            offer(r, nv * W_VECTOR + nb * W_BM25)

        # BM25 命中但向量没有的
        vec_paths = {r["path"] for r in vec_results}
        for r in bm25_results:
            if r["path"] not in vec_paths:
                offer(r, (r["bm25_score"] / bm25_max) * W_BM25)

        # 排序：精确直达 > 分数
        ranked = sorted(merged.values(), key=lambda x: x.get("score", 0), reverse=True)

        # 精确匹配的置顶
        final = []
        for e in exact:
            final.append({
                "path": e["path"], "content": e["content"], "heading": e.get("heading", ""),
                "chunk_index": e.get("chunk_index", 0),
                "similarity": 1.0, "matched_by": "exact",
            })
        for r in ranked:
            if r["path"] in exact_paths:
                continue
            if len(final) >= limit:
                break
            final.append({
                "path": r["path"], "content": r["content"], "heading": r.get("heading", ""),
                "chunk_index": r.get("chunk_index", 0),
                "similarity": round(r.get("score", 0), 6),
                "matched_by": "vector+bm25" if r["path"] in vec_paths else "bm25",
            })
        return final[:limit]

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
            elif parsed.path == "/search":
                q = params.get("query", "")
                limit = int(params.get("limit", 10))
                self._json(self.system.search(q, limit))
            elif parsed.path == "/index":
                self._json(self.system.index_workspace())
            elif parsed.path == "/stats":
                self._json(self.system.stats())
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
        with self.system.conn.cursor() as cur:
            cur.execute("""
                SELECT role, timestamp, content::text
                FROM conversations
                WHERE session_key = %s ORDER BY timestamp, id
            """, (key,))
            rows = cur.fetchall()
            return [{"role": r[0], "timestamp": str(r[1]), "content": r[2][:2000]} for r in rows]


def main():
    print("[SummerMemory v2.0] 启动中...")
    Handler.system = MemorySystem()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[SummerMemory v2.0] 端口 {PORT} 就绪，引擎 {OLLAMA_MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
