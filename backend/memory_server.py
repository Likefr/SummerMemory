#!/usr/bin/env python3
"""
SummerMemory HTTP Server
常驻服务，避免每次启动 Python 的开销
"""

import json
import sys
import time
import hashlib
import re
import asyncio
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

import requests
import psycopg2
import jieba
import websockets

# 配置
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "summer_memory",
    "user": "postgres",
    "password": "POIASD520--="
}

# Ollama 配置
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "quentinz/bge-small-zh-v1.5"

WORKSPACE = Path("/root/.openclaw/workspace")
PORT = 11435

# 分块参数
MAX_CHUNK_CHARS = 800  # 每块最大字符数（中文约 400-500 token，安全在 512 内）


def chunk_markdown(text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """
    按 Markdown 标题（##/###）+ 空行分段落，每块不超过 max_chars 字符。
    超长的块按 max_chars 硬切。空块被丢弃。
    """
    # 按标题行（## ... 或 ### ... 等）拆分，保留标题行
    # 模式：匹配行首的 ## 开头（至少2个#）
    header_pattern = re.compile(r'^(#{2,}\s.+)$', re.MULTILINE)

    parts = []
    last_end = 0
    for m in header_pattern.finditer(text):
        if m.start() > last_end:
            section = text[last_end:m.start()].strip()
            if section:
                parts.append(section)
        last_end = m.start()
    # 最后一段
    remaining = text[last_end:].strip()
    if remaining:
        parts.append(remaining)

    # 如果没有标题，整篇作为一段
    if not parts:
        stripped = text.strip()
        if stripped:
            parts = [stripped]
        else:
            return []

    # 每段如果太长，按空行再拆，或硬切
    chunks = []
    for part in parts:
        if len(part) <= max_chars:
            chunks.append(part)
        else:
            # 按空行再拆分
            sub_parts = re.split(r'\n\s*\n', part)
            current = ""
            for sp in sub_parts:
                sp = sp.strip()
                if not sp:
                    continue
                if len(current) + len(sp) + 2 <= max_chars:
                    if current:
                        current += "\n\n" + sp
                    else:
                        current = sp
                else:
                    if current:
                        chunks.append(current)
                    # 如果单段超过 max_chars，硬切
                    if len(sp) > max_chars:
                        for i in range(0, len(sp), max_chars):
                            chunks.append(sp[i:i + max_chars])
                    else:
                        current = sp
            if current:
                chunks.append(current)

    # 过滤空块
    return [c for c in chunks if c.strip()]


class MemorySystem:
    def __init__(self):
        self.conn = self._get_connection()
        self._ensure_tables()

    def _get_connection(self):
        """创建新的数据库连接"""
        return psycopg2.connect(**DB_CONFIG)

    def _ensure_connection(self):
        """检查连接是否有效，先 rollback 清理事务状态，无效则重连"""
        try:
            self.conn.rollback()
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            print("数据库连接已关闭，正在重连...")
            self.conn = self._get_connection()

    def _ensure_tables(self):
        with self.conn.cursor() as cur:
            # 1. 确保表存在（含 chunk_index 列）
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id SERIAL PRIMARY KEY,
                    path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector(512),
                    content_tsv TSVECTOR,
                    metadata JSONB DEFAULT '{}',
                    hash TEXT,
                    chunk_index INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)
            # 2. 如果表已存在但没有 content_tsv 列，添加它
            cur.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='memories' AND column_name='content_tsv'
                    ) THEN 
                        ALTER TABLE memories ADD COLUMN content_tsv TSVECTOR;
                    END IF;
                END $$;
            """)
            # 3. 如果表已存在但没有 chunk_index 列，添加它
            cur.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='memories' AND column_name='chunk_index'
                    ) THEN 
                        ALTER TABLE memories ADD COLUMN chunk_index INTEGER DEFAULT 0;
                    END IF;
                END $$;
            """)
            # 4. 创建索引
            cur.execute("""
                CREATE INDEX IF NOT EXISTS memories_embedding_idx 
                ON memories USING ivfflat (embedding vector_cosine_ops) 
                WITH (lists = 2);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS memories_path_idx ON memories (path);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS memories_hash_idx ON memories (hash);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS memories_path_chunk_idx ON memories (path, chunk_index);
            """)
            # 5. activity 日志表（如果不存在）
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memory_activity (
                    id SERIAL PRIMARY KEY,
                    action TEXT NOT NULL,
                    path TEXT,
                    query TEXT,
                    timestamp TIMESTAMP DEFAULT NOW()
                );
            """)
            self.conn.commit()

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """调用 Ollama 获取文本嵌入向量，失败返回 None"""
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/embeddings",
                json={"model": OLLAMA_MODEL, "prompt": text},
                timeout=15
            )
            if resp.status_code == 200:
                result = resp.json().get("embedding")
                if result and len(result) > 0:
                    return result
                print(f"Embedding API returned empty result")
                return None
            else:
                print(f"Embedding API error: {resp.status_code}")
                return None
        except Exception as e:
            print(f"Embedding error: {e}")
            return None

    def _segment_text(self, text: str) -> str:
        """为全文搜索分词"""
        return ' '.join(jieba.cut(text))

    def index_file(self, path: Path) -> Dict[str, Any]:
        """索引单个文件（按 chunk 拆分后逐块索引）"""
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            return {'path': str(path), 'status': 'error', 'message': str(e)}

        # 统一使用相对路径（memory/xxx），避免绝对路径导致重复
        rel_path = str(path).replace(str(WORKSPACE) + '/', '')

        # 过滤空文件
        if not content.strip():
            return {'path': str(path), 'status': 'skipped', 'message': 'empty file'}

        # 分块
        chunks = chunk_markdown(content, MAX_CHUNK_CHARS)
        if not chunks:
            chunks = [content[:MAX_CHUNK_CHARS]]

        # 提取文件级元数据
        metadata = {
            'size': path.stat().st_size,
            'mtime': datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            'total_chunks': len(chunks),
        }

        self._ensure_connection()

        # 检查该文件已有 chunk 的 hash 集合，用于判断是否全未变更
        new_hashes = [hashlib.md5(c.encode()).hexdigest() for c in chunks]
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT hash, chunk_index FROM memories WHERE path = %s ORDER BY chunk_index",
                (rel_path,)
            )
            existing_rows = cur.fetchall()

        # 快速判断：如果 chunk 数量一样且每个 hash 都一样，跳过
        existing_map = {row[1]: row[0] for row in existing_rows}
        if len(existing_rows) == len(chunks):
            all_same = True
            for i, h in enumerate(new_hashes):
                if existing_map.get(i) != h:
                    all_same = False
                    break
            if all_same:
                # 还需要确认 embedding 都存在
                with self.conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM memories WHERE path = %s AND embedding IS NOT NULL",
                        (rel_path,)
                    )
                    emb_count = cur.fetchone()[0]
                if emb_count == len(chunks):
                    return {'path': str(path), 'status': 'unchanged', 'chunks': len(chunks)}

        # 删除该文件的所有旧 chunk，重新插入
        with self.conn.cursor() as cur:
            # 同时清理可能的绝对路径旧记录
            cur.execute("DELETE FROM memories WHERE path IN (%s, %s)", (rel_path, str(path)))

        # 逐块写入
        status = 'indexed'
        for i, chunk_content in enumerate(chunks):
            chunk_hash = new_hashes[i]
            embedding = self.get_embedding(chunk_content[:MAX_CHUNK_CHARS])
            segmented = self._segment_text(chunk_content)
            chunk_meta = dict(metadata)
            chunk_meta['chunk_index'] = i
            chunk_meta['chunk_hash'] = chunk_hash

            with self.conn.cursor() as cur:
                if embedding is not None:
                    cur.execute("""
                        INSERT INTO memories (path, content, embedding, content_tsv, metadata, hash, chunk_index)
                        VALUES (%s, %s, %s::vector, to_tsvector('simple', %s), %s::jsonb, %s, %s)
                    """, (rel_path, chunk_content, embedding, segmented,
                          json.dumps(chunk_meta, ensure_ascii=False), chunk_hash, i))
                else:
                    cur.execute("""
                        INSERT INTO memories (path, content, content_tsv, metadata, hash, chunk_index)
                        VALUES (%s, %s, to_tsvector('simple', %s), %s::jsonb, %s, %s)
                    """, (rel_path, chunk_content, segmented,
                          json.dumps(chunk_meta, ensure_ascii=False), chunk_hash, i))

            if existing_map and i in existing_map:
                status = 'updated'

        self.conn.commit()
        return {'path': str(path), 'status': status, 'chunks': len(chunks)}

    def index_workspace(self) -> Dict[str, Any]:
        """索引工作区所有可索引的文件"""
        self._ensure_connection()
        results = {'indexed': 0, 'updated': 0, 'unchanged': 0, 'failed': 0, 'details': []}

        memory_dir = WORKSPACE / 'memory'
        if not memory_dir.exists():
            return results

        # 支持的文件扩展名
        extensions = {'.md', '.py', '.js', '.vue', '.ts', '.json', '.yaml', '.yml', '.html', '.css', '.txt'}

        for f in sorted(memory_dir.rglob('*')):
            if f.is_file() and f.suffix in extensions:
                # 跳过梦境目录和其他无关目录
                f_str = str(f)
                if '.dreams' in f_str or 'node_modules' in f_str:
                    continue
                if 'dreaming' in f_str:
                    continue
                result = self.index_file(f)
                results[result['status']] = results.get(result['status'], 0) + 1
                results['details'].append(result)

        self.conn.commit()
        # 记录活动
        self._log_activity('index_workspace', 'memory/', None)
        return results

    def _log_activity(self, action: str, path: str = None, query: str = None):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO memory_activity (action, path, query)
                    VALUES (%s, %s, %s)
                """, (action, path, query))
            self.conn.commit()
        except:
            pass
        # 向所有 WebSocket 客户端广播 activity 事件（过滤健康检查）
        if query != 'test':
            try:
                ws_manager.broadcast({
                    "type": "activity",
                    "action": action,
                    "path": path,
                    "query": query,
                })
            except Exception:
                pass

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """混合搜索：先尝试向量搜索，失败则回退到全文搜索"""
        self._ensure_connection()

        # 向量搜索
        embedding = self.get_embedding(query)
        if embedding:
            try:
                with self.conn.cursor() as cur:
                    cur.execute("""
                        SELECT path, content, metadata, chunk_index,
                               1 - (embedding <=> %s::vector) AS similarity
                        FROM memories
                        WHERE embedding IS NOT NULL
                        ORDER BY similarity DESC
                        LIMIT %s
                    """, (embedding, limit))
                    results = []
                    for row in cur.fetchall():
                        results.append({
                            'path': row[0],
                            'content': row[1][:500],
                            'metadata': row[2],
                            'chunk_index': row[3],
                            'similarity': round(row[4], 4)
                        })
                    # 广播搜索命中的文件路径
                    self._log_activity('search', path=results[0]['path'] if results else None, query=query)
                    return results
            except Exception as e:
                print(f"Vector search error: {e}")

        # 回退：全文搜索
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT path, content, metadata, chunk_index,
                       ts_rank(content_tsv, plainto_tsquery('simple', %s)) AS rank
                FROM memories
                WHERE content_tsv @@ plainto_tsquery('simple', %s)
                ORDER BY rank DESC
                LIMIT %s
            """, (query, query, limit))
            results = []
            for row in cur.fetchall():
                results.append({
                    'path': row[0],
                    'content': row[1][:500],
                    'metadata': row[2],
                    'chunk_index': row[3],
                    'similarity': round(row[4], 4)
                })
            # 广播搜索命中的文件路径
            self._log_activity('search', path=results[0]['path'] if results else None, query=query)
            return results

    def get_stats(self) -> Dict[str, Any]:
        """获取系统统计信息"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM memories")
            total_chunks = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT path) FROM memories")
            total_files = cur.fetchone()[0]

            cur.execute("""
                SELECT path, updated_at FROM memories 
                ORDER BY updated_at DESC LIMIT 1
            """)
            last = cur.fetchone()

            # 按目录统计（按文件去重）
            cur.execute("""
                SELECT SPLIT_PART(path, '/', 4) as dir, COUNT(DISTINCT path) as cnt
                FROM memories 
                GROUP BY dir 
                ORDER BY cnt DESC
            """)
            dirs = {row[0]: row[1] for row in cur.fetchall()}

        return {
            'total_files': total_files,
            'total_chunks': total_chunks,
            'total_memories': total_chunks,
            'unique_files': total_files,
            'last_updated': last[1].isoformat() if last else None,
            'directories': dirs
        }

    def get_graph_data(self) -> Dict[str, Any]:
        """获取关系图数据"""
        with self.conn.cursor() as cur:
            # 按文件 path 分组，统计实际 chunk 数
            cur.execute("""
                SELECT path, COUNT(*) as chunk_count,
                       MAX(updated_at) as last_updated
                FROM memories
                GROUP BY path
                ORDER BY path
            """)
            file_rows = cur.fetchall()

            nodes = []
            file_nodes = set()
            # 缓存每个文件的 metadata（取第一个 chunk 的）
            file_meta = {}
            cur.execute("""
                SELECT DISTINCT ON (path) path, metadata
                FROM memories
                ORDER BY path, chunk_index
            """)
            for row in cur.fetchall():
                file_meta[row[0]] = row[1] or {}

            for row in file_rows:
                path = row[0]
                chunk_count = row[1]
                filename = Path(path).name

                metadata = file_meta.get(path, {})
                size = metadata.get('size', 0)
                # 使用实际 chunk 记录数
                chunks = chunk_count

                node = {
                    'id': path,
                    'name': filename,
                    'type': 'file',
                    'val': max(1, min(10, size / 1000)),
                    'group': Path(path).parent.name or 'root',
                    'path': path,
                    'size': size,
                    'chunks': chunks,
                    'fileSize': size,
                    'label': filename,
                }
                file_nodes.add(path)
                nodes.append(node)

            # 构建链接
            links = []
            path_list = sorted(file_nodes)

            # 基于目录关系的链接
            for i, path1 in enumerate(path_list):
                p1 = Path(path1)
                for path2 in path_list[i+1:]:
                    p2 = Path(path2)
                    if p1.parent == p2.parent:
                        links.append({
                            'source': path1,
                            'target': path2,
                            'weight': 0.3
                        })
                    elif p1.stem[:10] == p2.stem[:10]:
                        links.append({
                            'source': path1,
                            'target': path2,
                            'weight': 0.5
                        })

            # 基于内容重叠的链接（逐 chunk 比较取最高相似度）
            with self.conn.cursor() as cur2:
                for i, path1 in enumerate(path_list):
                    for path2 in path_list[i+1:]:
                        cur2.execute("""
                            SELECT MAX(1 - (m1.embedding <=> m2.embedding)) AS similarity
                            FROM memories m1, memories m2
                            WHERE m1.path = %s AND m2.path = %s
                            AND m1.embedding IS NOT NULL AND m2.embedding IS NOT NULL
                        """, (path1, path2))
                        row = cur2.fetchone()
                        if row and row[0] is not None and row[0] > 0.8:
                            links.append({
                                'source': path1,
                                'target': path2,
                                'weight': float(row[0])
                            })

        return {
            'nodes': nodes,
            'links': links
        }

# ---- WebSocket 广播管理 ----

class WebSocketManager:
    """管理所有 WebSocket 客户端连接，并提供广播方法"""

    def __init__(self):
        self._clients: Set = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def register(self, ws):
        self._clients.add(ws)

    def unregister(self, ws):
        self._clients.discard(ws)

    def broadcast(self, message: dict):
        """线程安全地向所有 WS 客户端广播 JSON 消息"""
        if not self._clients or not self._loop:
            return
        data = json.dumps(message, ensure_ascii=False)
        # 从任意线程调度到 asyncio 事件循环
        for ws in list(self._clients):
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future, self._safe_send(ws, data)
            )

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
    try:
        # 保持连接，等待客户端断开
        async for _ in websocket:
            pass
    except websockets.ConnectionClosed:
        pass
    finally:
        ws_manager.unregister(websocket)


def _run_ws_server():
    """在独立线程中运行的 asyncio 事件循环"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ws_manager.set_loop(loop)

    async def start():
        return await websockets.serve(
            _ws_handler,
            "0.0.0.0",
            8890,
            loop=loop,
        )

    server = loop.run_until_complete(start())
    print(f"WebSocket server running on port 8890")
    loop.run_forever()


# ---- 全局 MemorySystem 实例 ----

memory = MemorySystem()

class MemoryHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 每次请求前确保连接有效
        memory._ensure_connection()
        memory.conn.rollback()  # 每次请求前清理可能失败的 transaction
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        params = urllib.parse.parse_qs(parsed_path.query)

        # 公开端点
        if path == '/search':
            query = params.get('query', [''])[0]
            limit = min(int(params.get('limit', [5])[0]), 20)
            result = memory.search(query, limit)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())

        elif path == '/activity':
            limit = min(int(params.get('limit', [10])[0]), 50)
            with memory.conn.cursor() as cur:
                cur.execute("""
                    SELECT action, path, query, timestamp
                    FROM memory_activity
                    ORDER BY timestamp DESC
                    LIMIT %s
                """, (limit,))
                activities = []
                for row in cur.fetchall():
                    activities.append({
                        'timestamp': row[3].isoformat(),
                        'action': row[0],
                        'path': row[1],
                        'query': row[2]
                    })
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(activities, ensure_ascii=False).encode())

        elif path == '/stats':
            result = memory.get_stats()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())

        elif path == '/graph-data':
            result = memory.get_graph_data()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())

        elif path == '/version':
            try:
                memory._ensure_connection()
                memory.conn.rollback()
                with memory.conn.cursor() as cur:
                    cur.execute("SELECT EXTRACT(EPOCH FROM MAX(updated_at))::bigint FROM memories")
                    result = cur.fetchone()
                    version = result[0] if result and result[0] else 0
            except Exception:
                memory.conn.rollback()
                version = 0
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                'version': version,
                'frontend': 'v260612.0855'
            }).encode())

        elif path == '/timeline':
            with memory.conn.cursor() as cur:
                cur.execute("""
                    SELECT DATE(created_at) as d, COUNT(DISTINCT path) as cnt,
                           json_agg(DISTINCT path) as paths
                    FROM memories 
                    GROUP BY d 
                    ORDER BY d
                """)
                timeline = []
                for row in cur.fetchall():
                    d, cnt, paths = row
                    file_names = [Path(p).name for p in (paths or [])]
                    timeline.append({
                        'date': d.isoformat() if d else '',
                        'count': cnt,
                        'files': file_names[:20]
                    })
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'timeline': timeline}).encode())

        # 内部端点 - 只允许本地访问
        elif path == '/index':
            client_ip = self.client_address[0]
            if client_ip not in ('127.0.0.1', '::1', 'localhost'):
                self.send_response(403)
                self.end_headers()
                return
            memory._ensure_connection()
            result = memory.index_workspace()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # 禁用日志

if __name__ == '__main__':
    # 启动 WebSocket 服务线程
    ws_thread = threading.Thread(target=_run_ws_server, daemon=True, name="ws-server")
    ws_thread.start()

    # 启动 HTTP 服务（阻塞主线程）
    server = HTTPServer(('0.0.0.0', PORT), MemoryHandler)
    print(f"SummerMemory HTTP server running on port {PORT}")
    server.serve_forever()
