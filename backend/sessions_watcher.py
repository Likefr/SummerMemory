#!/usr/bin/env python3
"""Sessions JSONL watcher - 实时归档 OpenClaw 会话消息到 SummerMemory conversations 表

监控 /root/.openclaw/agents/main/sessions/*.jsonl 文件变化，增量解析新行，
把 user/assistant 消息写入 conversations 表（纯归档，不进搜索）。

用法: sessions_watcher.py [--once]  (默认常驻)
"""
import json
import os
import sys
import time
import subprocess
from pathlib import Path

import psycopg2

SESSIONS_DIR = Path("/root/.openclaw/agents/main/sessions")
STATE_FILE = Path("/root/.openclaw/workspace/projects/SummerMemory/backend/.watcher_state.json")

state = {}

# 直连 PostgreSQL（Docker 容器映射到 127.0.0.1:5432）
_conn = None

def _ensure_conn():
    global _conn
    if _conn is not None and _conn.closed == 0:
        return _conn
    _conn = psycopg2.connect(
        host='127.0.0.1', port=5432, dbname='summer_memory',
        user='postgres', password='POIASD520--=', connect_timeout=5)
    _conn.autocommit = False
    return _conn


def resolve_session_key(session_id):
    """将 sessionId (agent:main:xxx) 解析为 dashboard key（如果存在映射）"""
    try:
        conn = _ensure_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT dashboard_key FROM session_key_map WHERE jsonl_uuid = %s",
                (session_id,))
            row = cur.fetchone()
            if row:
                return row[0]
    except Exception:
        pass
    return session_id


def db_insert(session_key, role, content, timestamp, seq=None, session_file=None):
    """psycopg2 直连插入，内容+时间双重去重（防 hook/watcher 双路重复）"""
    content_json = json.dumps(content, ensure_ascii=False)
    conn = _ensure_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO conversations (session_key, seq, session_file, role, content, timestamp)
                SELECT %s, %s, %s, %s, %s::jsonb, %s::timestamptz
                WHERE NOT EXISTS (
                    SELECT 1 FROM conversations
                    WHERE session_key = %s AND role = %s
                    AND content::text = %s
                    AND timestamp >= %s::timestamptz - interval '5 seconds'
                )
            """, (session_key, seq, session_file, role, content_json, timestamp,
                   session_key, role, content_json, timestamp))
            inserted = cur.rowcount
        conn.commit()
        return inserted
    except Exception as e:
        conn.rollback()
        print(f"db_insert error: {e}", file=sys.stderr, flush=True)
        # 连接坏了就重建
        try:
            _conn.close()
        except Exception:
            pass
        global _conn_ref
        _conn = None
        return 0


def load_state():
    global state
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except Exception:
            state = {}


def save_state():
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.rename(STATE_FILE)


def archive_file(path: Path):
    """解析一个 jsonl 文件的新增行"""
    key = str(path)
    offset = state.get(key, {}).get("offset", 0)
    mtime = state.get(key, {}).get("mtime", 0)

    try:
        st = os.stat(path)
        if st.st_size < offset:
            offset = 0  # 文件被重建，从头读
        if st.st_mtime == mtime and st.st_size == offset:
            return  # 无变化
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            new_data = f.read()
            new_offset = f.tell()
    except FileNotFoundError:
        return

    if not new_data:
        return

    session_key = f"agent:main:{path.stem.split('_')[-1]}"
    session_key = resolve_session_key(session_key)  # 优先用 dashboard key，/clear 后同一会话不断裂
    session_file = path.name
    # seq 从当前文件已归档的行数开始累计
    base_seq = state.get(key, {}).get("seq", 0)
    inserted = 0
    for line in new_data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "message":
            continue
        msg = entry.get("message", {})
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            parts = []
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text":
                    parts.append(c.get("text", ""))
                elif c.get("type") == "toolCall":
                    # 折中方案：只记 AI 干了什么（命令名+参数摘要），不记返回结果
                    name = c.get("name", "?")
                    args = c.get("arguments", {})
                    # 参数取摘要：command/url/query/path 等常见字段，截 200 字
                    summary = ""
                    for f in ("command", "url", "query", "path", "name", "action", "prompt"):
                        if isinstance(args, dict) and args.get(f):
                            summary = str(args[f]).replace("\n", " ")[:200]
                            break
                    if not summary and isinstance(args, dict):
                        summary = str(args)[:200]
                    parts.append(f"[工具 {name}] {summary}")
            text = "\n".join(parts)
        elif isinstance(content, str):
            text = content
        else:
            text = ""
        if not text.strip():
            continue
        ts = entry.get("timestamp", "")
        seq = base_seq + inserted
        db_insert(session_key, role, text, ts, seq=seq, session_file=session_file)
        inserted += 1

    state[key] = {"offset": new_offset, "mtime": st.st_mtime, "seq": base_seq + inserted}
    if inserted:
        print(f"[{time.strftime('%H:%M:%S')}] {path.name}: archived {inserted} msgs", flush=True)


def scan_all():
    for p in SESSIONS_DIR.glob("*.jsonl"):
        if p.name.endswith(".trajectory.jsonl"):
            continue
        archive_file(p)


def sync_key_map():
    """把 sessions.json 的 dashboard→uuid 映射快照进库（会话删除后映射仍在）"""
    try:
        with open('/root/.openclaw/agents/main/sessions/sessions.json') as f:
            sidx = json.load(f)
        conn = _ensure_conn()
        with conn.cursor() as cur:
            for key, entry in sidx.items():
                sid = entry.get('sessionId')
                if not sid or ':dashboard:' not in key:
                    continue
                cur.execute("""
                    INSERT INTO session_key_map (dashboard_key, jsonl_uuid, session_file)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (dashboard_key) DO UPDATE
                    SET jsonl_uuid = EXCLUDED.jsonl_uuid, session_file = EXCLUDED.session_file, mapped_at = NOW()
                """, (key, f"agent:main:{sid}", entry.get('sessionFile', '')))
        conn.commit()
    except Exception as e:
        print(f"sync_key_map error: {e}", file=sys.stderr, flush=True)


def main():
    once = "--once" in sys.argv
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    load_state()
    sync_key_map()
    scan_all()
    save_state()
    if once:
        return
    while True:
        time.sleep(2)
        scan_all()
        save_state()
        sync_key_map()


if __name__ == "__main__":
    main()
