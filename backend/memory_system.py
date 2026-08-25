#!/usr/bin/env python3
"""SummerMemory v2.0 CLI 入口 — 薄客户端，转发到 HTTP 服务"""
import sys, json, urllib.parse, urllib.request

SERVER_URL = "http://localhost:11435"

def search(query, limit=10):
    """搜索记忆（默认返回10条，v2 提升召回）"""
    params = urllib.parse.urlencode({"query": query, "limit": limit})
    url = f"{SERVER_URL}/search?{params}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode())

def conv_list(keyword=None):
    """列出归档会话"""
    url = f"{SERVER_URL}/conv/list"
    if keyword:
        url += "?" + urllib.parse.urlencode({"q": keyword})
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode())

def conv_get(session_key):
    """获取完整会话"""
    # dashboard key 自动转 UUID（兼容 webchat 复制的 key）
    if "dashboard:" in session_key:
        import sessions_keymap
        session_key = sessions_keymap.resolve(session_key) or session_key
    url = f"{SERVER_URL}/conv/get?" + urllib.parse.urlencode({"key": session_key})
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode())

def stats():
    with urllib.request.urlopen(f"{SERVER_URL}/stats", timeout=10) as response:
        return json.loads(response.read().decode())

def index():
    with urllib.request.urlopen(f"{SERVER_URL}/index", timeout=300) as response:
        return json.loads(response.read().decode())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: memory_system.py search|index|stats|conv <参数>")
        sys.exit(1)
    cmd = sys.argv[1]
    try:
        if cmd == "search" and len(sys.argv) >= 3:
            q = " ".join(sys.argv[2:])
            print(json.dumps(search(q), ensure_ascii=False, indent=2))
        elif cmd == "index":
            print(json.dumps(index(), ensure_ascii=False, indent=2))
        elif cmd == "stats":
            print(json.dumps(stats(), ensure_ascii=False, indent=2))
        elif cmd == "conv" and sys.argv[2] == "list":
            kw = sys.argv[3] if len(sys.argv) > 3 else None
            print(json.dumps(conv_list(kw), ensure_ascii=False, indent=2))
        elif cmd == "conv" and sys.argv[2] == "get" and len(sys.argv) >= 4:
            print(json.dumps(conv_get(sys.argv[3]), ensure_ascii=False, indent=2))
        else:
            print("未知命令")
            sys.exit(1)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
