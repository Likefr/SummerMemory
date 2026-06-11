#!/usr/bin/env python3
"""
SummerMemory CLI
调用 HTTP 服务的命令行工具
"""

import json
import sys
import urllib.request
import urllib.parse

SERVER_URL = "http://localhost:11435"

def search(query, limit=5):
    params = urllib.parse.urlencode({"query": query, "limit": limit})
    url = f"{SERVER_URL}/search?{params}"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode())

def stats():
    url = f"{SERVER_URL}/stats"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode())

def index():
    url = f"{SERVER_URL}/index"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: memory_system.py [search|stats|index] [args...]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "search":
        if len(sys.argv) < 3:
            print("Usage: memory_system.py search <query>")
            sys.exit(1)
        query = " ".join(sys.argv[2:])
        result = search(query)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif command == "stats":
        result = stats()
        print(json.dumps(result, indent=2))
    
    elif command == "index":
        result = index()
        print(json.dumps(result, indent=2))
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
