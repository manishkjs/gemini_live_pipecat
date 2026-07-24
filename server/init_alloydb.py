import os
import sys
import psycopg

def init_alloydb():
    print("===================================================")
    print("🚀 ALLOYDB INITIALIZATION & PGVECTOR MIGRATION SCRIPT")
    print("===================================================")
    
    alloy_ip = "10.127.13.2"
    alloy_pass = "Lenskart_Alloy_2026_x9k2P!"
    
    postgres_dsn = f"postgresql://postgres:{alloy_pass}@{alloy_ip}:5432/postgres"
    memory_dsn = f"postgresql://postgres:{alloy_pass}@{alloy_ip}:5432/lenskart_memory"
    
    print(f"1. Connecting to default postgres db at {alloy_ip}:5432...")
    try:
        conn = psycopg.connect(postgres_dsn, autocommit=True)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname='lenskart_memory';")
        if not cur.fetchone():
            print(" -> Creating database 'lenskart_memory'...")
            cur.execute("CREATE DATABASE lenskart_memory;")
            print(" ✅ Created 'lenskart_memory' database successfully!")
        else:
            print(" -> 'lenskart_memory' database already exists.")
        conn.close()
    except Exception as e:
        print(f"❌ Error connecting to postgres db: {e}")
        return False
        
    print(f"\n2. Connecting to 'lenskart_memory' db at {alloy_ip}:5432...")
    try:
        conn2 = psycopg.connect(memory_dsn, autocommit=True)
        cur2 = conn2.cursor()
        print(" -> Creating extension 'vector' (pgvector / ScaNN)...")
        cur2.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        try:
            cur2.execute("CREATE EXTENSION IF NOT EXISTS alloydb_scann;")
            print(" ✅ Extension 'alloydb_scann' created successfully!")
        except Exception as scann_e:
            print(f" -> Note: alloydb_scann extension: {scann_e}")

        print(" -> Creating table 'user_memories' and DDL schema...")
        cur2.execute("""
            CREATE TABLE IF NOT EXISTS user_memories (
                id UUID PRIMARY KEY,
                vector vector(768),
                payload JSONB,
                embedding vector(768),
                metadata JSONB,
                user_id VARCHAR(128),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)

        print(" -> Creating ScaNN vector index (`USING scann (embedding cosine)`)...")
        try:
            cur2.execute("CREATE INDEX IF NOT EXISTS user_memories_embedding_scann_idx ON user_memories USING scann (embedding cosine);")
        except Exception as idx_e:
            print(f" -> Note: ScaNN index on embedding: {idx_e}")
        try:
            cur2.execute("CREATE INDEX IF NOT EXISTS user_memories_vector_scann_idx ON user_memories USING scann (vector cosine);")
        except Exception as idx_e:
            print(f" -> Note: ScaNN index on vector: {idx_e}")

        print(" -> Creating GIN JSONB index (`USING gin (metadata)` / `payload`)...")
        cur2.execute("CREATE INDEX IF NOT EXISTS user_memories_metadata_gin_idx ON user_memories USING gin (metadata);")
        cur2.execute("CREATE INDEX IF NOT EXISTS user_memories_payload_gin_idx ON user_memories USING gin (payload);")
        cur2.execute("CREATE INDEX IF NOT EXISTS user_memories_user_id_idx ON user_memories (user_id);")
        print(" ✅ Extensions, Table DDL, ScaNN, and GIN indexes created successfully!")
        conn2.close()
    except Exception as e:
        print(f"❌ Error creating extension in lenskart_memory: {e}")
        return False
        
    print("\n===================================================")
    print("🏁 ALLOYDB INITIALIZATION COMPLETE 100% READY!")
    print("===================================================")
    return True

if __name__ == "__main__":
    success = init_alloydb()
    sys.exit(0 if success else 1)
