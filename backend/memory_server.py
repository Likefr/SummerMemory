#!/usr/bin/env python3
"""
SummerMemory HTTP Server
常驻服务，避免每次启动 Python 的开销
"""

import json
import sys
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

import requests
import psycopg2
import jieba

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
            # 1. 确保表存在
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id SERIAL PRIMARY KEY,
                    path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector(512),
                    content_tsv TSVECTOR,
                    metadata JSONB DEFAULT '{}',
                    hash TEXT,
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
            # 3. 创建索引（列已存在）
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
            # 4. activity 日志表（如果不存在）
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
    
    def get_embedding(self, text: str) -> List[float]:
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
        """索引单个文件"""
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            return {'path': str(path), 'status': 'error', 'message': str(e)}
        
        # 统一使用相对路径（memory/xxx），避免绝对路径导致重复
        rel_path = str(path).replace(str(WORKSPACE) + '/', '')
        
        content_hash = hashlib.md5(content.encode()).hexdigest()
        
        # 检查是否已索引且未变更（同时检查相对路径和绝对路径）
        with self.conn.cursor() as cur:
            cur.execute("SELECT hash, id, embedding FROM memories WHERE path IN (%s, %s) ORDER BY updated_at DESC LIMIT 1", (rel_path, str(path)))
            existing = cur.fetchone()
            if existing and existing[0] == content_hash and existing[2] is not None:
                return {'path': str(path), 'status': 'unchanged'}
        
        # 生成 embedding（失败时跳过向量写入）
        embedding = self.get_embedding(content[:2000])  # 截取前2000字符
        
        # 分词
        segmented = self._segment_text(content)
        
        # 提取元数据（文件大小、修改时间）
        metadata = {
            'size': path.stat().st_size,
            'mtime': datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        }
        
        self._ensure_connection()
        with self.conn.cursor() as cur:
            if embedding is not None:
                # embedding 成功：正常写入向量
                if existing:
                    cur.execute("""
                        UPDATE memories 
                        SET path = %s, content = %s, embedding = %s::vector, content_tsv = to_tsvector('simple', %s),
                            metadata = %s::jsonb, hash = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (rel_path, content, embedding, segmented, json.dumps(metadata, ensure_ascii=False), content_hash, existing[1]))
                else:
                    cur.execute("""
                        INSERT INTO memories (path, content, embedding, content_tsv, metadata, hash)
                        VALUES (%s, %s, %s::vector, to_tsvector('simple', %s), %s::jsonb, %s)
                    """, (rel_path, content, embedding, segmented, json.dumps(metadata, ensure_ascii=False), content_hash))
            else:
                # embedding 失败：只写文本，不写向量（下次索引时补上）
                if existing:
                    cur.execute("""
                        UPDATE memories 
                        SET path = %s, content = %s, content_tsv = to_tsvector('simple', %s),
                            metadata = %s::jsonb, hash = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (rel_path, content, segmented, json.dumps(metadata, ensure_ascii=False), content_hash, existing[1]))
                else:
                    cur.execute("""
                        INSERT INTO memories (path, content, content_tsv, metadata, hash)
                        VALUES (%s, %s, to_tsvector('simple', %s), %s::jsonb, %s)
                    """, (rel_path, content, segmented, json.dumps(metadata, ensure_ascii=False), content_hash))
        
        self.conn.commit()
        return {'path': str(path), 'status': 'updated' if existing else 'indexed'}
    
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
    
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """混合搜索：先尝试向量搜索，失败则回退到全文搜索"""
        self._ensure_connection()
        self._log_activity('search', query=query)
        
        # 向量搜索
        embedding = self.get_embedding(query)
        if embedding:
            try:
                with self.conn.cursor() as cur:
                    cur.execute("""
                        SELECT path, content, metadata, 
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
                            'content': row[1][:500],  # 截取前500字符
                            'metadata': row[2],
                            'similarity': round(row[3], 4)
                        })
                    return results
            except Exception as e:
                print(f"Vector search error: {e}")
        
        # 回退：全文搜索
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT path, content, metadata,
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
                    'similarity': round(row[3], 4)
                })
            return results
    
    def get_stats(self) -> Dict[str, Any]:
        """获取系统统计信息"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM memories")
            total = cur.fetchone()[0]
            
            cur.execute("""
                SELECT path, updated_at FROM memories 
                ORDER BY updated_at DESC LIMIT 1
            """)
            last = cur.fetchone()
            
            cur.execute("""
                SELECT COUNT(DISTINCT path) FROM memories
            """)
            unique_paths = cur.fetchone()[0]
            
            # 按目录统计
            cur.execute("""
                SELECT SPLIT_PART(path, '/', 4) as dir, COUNT(*) as cnt
                FROM memories 
                GROUP BY dir 
                ORDER BY cnt DESC
            """)
            dirs = {row[0]: row[1] for row in cur.fetchall()}
        
        # 统计总chunks数
        with self.conn.cursor() as cur:
            cur.execute("SELECT SUM(LENGTH(content) / 500) FROM memories WHERE content IS NOT NULL")
            total_chunks = cur.fetchone()[0] or len(path_list)
        
        return {
            'total_files': unique_paths,
            'total_chunks': int(total_chunks),
            'total_memories': total,
            'unique_files': unique_paths,
            'last_updated': last[1].isoformat() if last else None,
            'directories': dirs
        }
    
    def get_graph_data(self) -> Dict[str, Any]:
        """获取关系图数据"""
        with self.conn.cursor() as cur:
            # 获取所有节点（按 path 去重）
            cur.execute("""
                SELECT DISTINCT ON (path) path, content, metadata
                FROM memories
                ORDER BY path, updated_at DESC
            """)
            nodes = []
            file_nodes = set()
            path_counter = {}
            for row in cur.fetchall():
                path = row[0]
                # 提取文件名作显示名
                filename = Path(path).name
                if path not in path_counter:
                    path_counter[path] = 1
                else:
                    path_counter[path] += 1
                
                # 确定节点类型
                metadata = row[2] or {}
                size = metadata.get('size', 0)
                
                # 估算chunks数（基于文件大小，每500字一个chunk）
                content = row[1] or ''
                chunks = max(1, len(content) // 500)
                
                node = {
                    'id': path,
                    'name': filename,
                    'type': 'file',
                    'val': max(1, min(10, size / 1000)),  # 归一化大小
                    'group': Path(path).parent.name or 'root',
                    'path': path,
                    'size': size,
                    'chunks': chunks,
                    'fileSize': size,
                    'label': filename,
                }
                file_nodes.add(path)
                nodes.append(node)
            
            # 构建链接（基于内容相似度和路径关系）
            links = []
            path_list = sorted(file_nodes)
            
            # 基于目录关系的链接
            for i, path1 in enumerate(path_list):
                p1 = Path(path1)
                for path2 in path_list[i+1:]:
                    p2 = Path(path2)
                    # 如果文件在同一目录，建立链接
                    if p1.parent == p2.parent:
                        links.append({
                            'source': path1,
                            'target': path2,
                            'weight': 0.3
                        })
                    # 如果文件名相关（共享前缀）
                    elif p1.stem[:10] == p2.stem[:10]:
                        links.append({
                            'source': path1,
                            'target': path2,
                            'weight': 0.5
                        })
            
            # 基于内容重叠的链接
            with self.conn.cursor() as cur:
                for i, path1 in enumerate(path_list):
                    for path2 in path_list[i+1:]:
                        cur.execute("""
                            SELECT 1 - (m1.embedding <=> m2.embedding) AS similarity
                            FROM memories m1, memories m2
                            WHERE m1.path = %s AND m2.path = %s
                            AND m1.embedding IS NOT NULL AND m2.embedding IS NOT NULL
                            LIMIT 1
                        """, (path1, path2))
                        row = cur.fetchone()
                        if row and row[0] > 0.8:
                            links.append({
                                'source': path1,
                                'target': path2,
                                'weight': row[0]
                            })
        
        return {
            'nodes': nodes,
            'links': links
        }

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
            limit = min(int(params.get('limit', [5])[0]), 20)  # 限制最多20条
            result = memory.search(query, limit)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
        
        elif path == '/activity':
            # 返回最近的活动记录
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
            # 返回数据版本（时间戳）+ 前端版本号
            try:
                memory._ensure_connection()
                memory.conn.rollback()  # 清理可能的失败事务
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
                'frontend': 'v260608.1920'
            }).encode())
        
        elif path == '/timeline':
            # 时间轴数据：按天统计记忆数量
            with memory.conn.cursor() as cur:
                cur.execute("""
                    SELECT DATE(created_at) as d, COUNT(*) as cnt,
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
                        'files': file_names[:20]  # 最多显示20个文件名
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
    server = HTTPServer(('0.0.0.0', PORT), MemoryHandler)
    print(f"SummerMemory server running on port {PORT}")
    server.serve_forever()
