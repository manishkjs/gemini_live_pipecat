import os
import sys
import psycopg
import json

def migrate_to_alloydb():
    print("===================================================")
    print("🚀 MIGRATING MEMORY RECORDS TO ALLOYDB PRIVATE VPC")
    print("===================================================")
    
    old_dsn = "postgresql://lenskart_app:Lenskart_PgV_2026_x9k2P!@136.114.180.75:5432/lenskart_memory"
    alloy_dsn = "postgresql://postgres:Lenskart_Alloy_2026_x9k2P!@10.127.13.2:5432/lenskart_memory"
    
    print("1. Reading records from old Cloud SQL db...")
    try:
        conn1 = psycopg.connect(old_dsn)
        cur1 = conn1.cursor()
        cur1.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename='user_memories';")
        if not cur1.fetchone():
            print(" -> No user_memories table in old db yet.")
            return True
            
        cur1.execute("SELECT id, vector, payload FROM user_memories;")
        rows = cur1.fetchall()
        print(f" -> Found {len(rows)} memory records in old db!")
        conn1.close()
    except Exception as e:
        print(f"❌ Error reading old db: {e}")
        return False
        
    if not rows:
        print(" -> Nothing to copy.")
        return True
        
    print("2. Writing records into AlloyDB (10.127.13.2:5432)...")
    try:
        conn2 = psycopg.connect(alloy_dsn, autocommit=True)
        cur2 = conn2.cursor()
        
        # Ensure user_memories table exists with vector column
        cur2.execute("""
            CREATE TABLE IF NOT EXISTS user_memories (
                id VARCHAR(255) PRIMARY KEY,
                vector vector(768),
                payload JSONB
            );
        """)
        
        count = 0
        for r_id, r_vec, r_payload in rows:
            payload_json = json.dumps(r_payload) if isinstance(r_payload, dict) else r_payload
            cur2.execute("""
                INSERT INTO user_memories (id, vector, payload)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    vector = EXCLUDED.vector,
                    payload = EXCLUDED.payload;
            """, (r_id, r_vec, payload_json))
            count += 1
            
        print(f" ✅ Successfully migrated and indexed {count} memory records in AlloyDB Private VPC!")
        conn2.close()
    except Exception as e:
        print(f"❌ Error writing to AlloyDB: {e}")
        return False
        
    print("===================================================")
    print("🏁 DATA MIGRATION TO ALLOYDB COMPLETE!")
    print("===================================================")
    return True

if __name__ == "__main__":
    success = migrate_to_alloydb()
    sys.exit(0 if success else 1)
