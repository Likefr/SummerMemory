-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 记忆表（v2：1024维向量 + 标题 + heading链 + mtime元数据）
CREATE TABLE IF NOT EXISTS memories (
    id SERIAL PRIMARY KEY,
    path TEXT NOT NULL,
    heading TEXT,
    content TEXT NOT NULL,
    embedding vector(1024),
    content_tsv TSVECTOR,
    hash TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- tsvector 自动更新触发器
CREATE OR REPLACE FUNCTION memories_tsv_trigger() RETURNS trigger AS \$\$
BEGIN
    NEW.content_tsv := to_tsvector('simple', COALESCE(NEW.heading, '') || ' ' || NEW.content);
    RETURN NEW;
END;
\$\$ LANGUAGE plpgsql;

CREATE TRIGGER memories_tsv_update
    BEFORE INSERT OR UPDATE ON memories
    FOR EACH ROW EXECUTE FUNCTION memories_tsv_trigger();

-- HNSW 向量索引（v2 升级：IVFFlat → HNSW，更准更快）
CREATE INDEX IF NOT EXISTS memories_embedding_idx
    ON memories USING hnsw (embedding vector_cosine_ops);

-- 路径索引
CREATE INDEX IF NOT EXISTS memories_path_idx ON memories (path);

-- 哈希索引（增量索引用）
CREATE INDEX IF NOT EXISTS memories_hash_idx ON memories (hash);

-- 会话归档表
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    session_key TEXT NOT NULL,
    seq INTEGER DEFAULT 0,
    session_file TEXT,
    role TEXT NOT NULL,
    content JSONB NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- 归档去重索引
CREATE UNIQUE INDEX IF NOT EXISTS conv_unique_idx
    ON conversations (session_key, timestamp, role);

CREATE INDEX IF NOT EXISTS conv_session_idx ON conversations (session_key);
CREATE INDEX IF NOT EXISTS conv_time_idx ON conversations (timestamp);

-- 图谱质心表（v2：零内存开销，增量刷新）
CREATE TABLE IF NOT EXISTS graph_centroids (
    path TEXT PRIMARY KEY,
    centroid vector(1024),
    chunk_count INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- session key 映射表（dashboard key → sessionId）
CREATE TABLE IF NOT EXISTS session_key_map (
    dashboard_key TEXT PRIMARY KEY,
    jsonl_uuid TEXT NOT NULL,
    session_file TEXT,
    mapped_at TIMESTAMP DEFAULT NOW()
);
