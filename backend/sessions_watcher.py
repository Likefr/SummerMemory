#!/usr/bin/env python3
"""Sessions watcher - 实时归档 OpenClaw 会话消息到 SummerMemory conversations 表

新版 OpenClaw(2026.8+) 会话不再写入 JSONL 文件，全部存在 agent SQLite:
  /root/.openclaw/agents/main/agent/openclaw-agent.sqlite
  - transcript_events(session_id, seq, event_json)  事件流(含 user/assistant 消息)
  - session_windows(session_id, session_key)        会话身份映射(稳定 key)

本脚本只读轮询该库新增消息事件，归档到 SummerMemory conversations 表(纯归档，不进搜索)。
WAL 模式下只读连接不影响网关写入。

用法: sessions_watcher.py [--once]  (默认常驻)
"""
import json
import sys
import time
import sqlite3
from pathlib import Path

import psycopg2

AGENT_DB = Path("/root/.openclaw/agents/main/agent/openclaw-agent.sqlite")
STATE_FILE = Path("/root/.openclaw/workspace/projects/SummerMemory/backend/.watcher_state.json")
POLL_SECONDS = 2

# state 结构: { "<session_id>": {"seq": 已归档最大事件seq, "archived": 已写入条数} }
state = {}

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


def db_insert(session_key, role, content, timestamp, seq=None, session_file=None):
    """psycopg2 直连插入，内容+时间双重去重(防重复归档)"""
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
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None
        return 0


def load_state():
    global state
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except Exception:
            state = {}
    # 兼容旧格式(按 jsonl 路径记): 旧格式不是 {"<id>":{"seq":..}} 则重置
    if not all(isinstance(v, dict) and "seq" in v for v in state.values()):
        state = {}


def save_state():
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.rename(STATE_FILE)


def _extract(entry):
    """从事件 JSON 提取可归档文本;非 user/assistant 消息返回 None"""
    if entry.get("type") != "message":
        return None
    msg = entry.get("message", {})
    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None
    content = msg.get("content")
    if isinstance(content, list):
        parts = []
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") == "toolCall":
                # 只记 AI 干了什么(命令名+参数摘要)，不记返回结果
                name = c.get("name", "?")
                args = c.get("arguments", {})
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
        return None
    return role, text


def scan_all():
    """轮询新库：每会话归档 seq 大于上次进度的消息事件"""
    if not AGENT_DB.exists():
        return
    try:
        db = sqlite3.connect(f"file:{AGENT_DB}?mode=ro", uri=True)
        db.execute("PRAGMA query_only=1")
    except sqlite3.Error as e:
        print(f"open agent db error: {e}", file=sys.stderr, flush=True)
        return
    try:
        heads = db.execute("""
            SELECT e.session_id, w.session_key, MAX(e.seq)
            FROM transcript_events e
            JOIN session_windows w ON w.session_id = e.session_id
            GROUP BY e.session_id, w.session_key
        """).fetchall()
        for session_id, session_key, max_seq in heads:
            last = state.get(session_id, {}).get("seq", 0)
            if max_seq <= last:
                continue
            rows = db.execute(
                "SELECT seq, event_json FROM transcript_events"
                " WHERE session_id = ? AND seq > ? ORDER BY seq",
                (session_id, last)).fetchall()
            base = state.get(session_id, {}).get("archived", 0)
            inserted = 0
            for seq, event_json in rows:
                try:
                    entry = json.loads(event_json)
                except json.JSONDecodeError:
                    continue
                extracted = _extract(entry)
                if not extracted:
                    continue
                role, text = extracted
                ts = entry.get("timestamp", "")
                db_insert(session_key, role, text, ts,
                          seq=base + inserted, session_file=f"{session_id[:8]}.sqlite")
                inserted += 1
            state[session_id] = {"seq": max_seq, "archived": base + inserted}
            if inserted:
                print(f"[{time.strftime('%H:%M:%S')}] {session_key}: archived {inserted} msgs", flush=True)
    finally:
        db.close()


def main():
    once = "--once" in sys.argv
    load_state()
    scan_all()
    save_state()
    if once:
        return
    while True:
        time.sleep(POLL_SECONDS)
        scan_all()
        save_state()


if __name__ == "__main__":
    main()