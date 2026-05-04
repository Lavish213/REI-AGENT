import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(override=False)

SUPABASE_URL = os.environ["SUPABASE_URL"]
DB_PASSWORD = os.environ.get("SUPABASE_DB_PASSWORD") or os.environ.get("DB_PASSWORD")

if not DB_PASSWORD:
    print("ERROR: set SUPABASE_DB_PASSWORD or DB_PASSWORD in .env")
    print("Get it from: Supabase dashboard > Project Settings > Database > Connection string")
    sys.exit(1)

ref = SUPABASE_URL.replace("https://", "").split(".")[0]
conn_str = f"postgresql://postgres:{DB_PASSWORD}@db.{ref}.supabase.co:5432/postgres?sslmode=require"

migration = Path(__file__).parent.parent / "supabase" / "migrations" / "20260504_add_missing_properties_columns.sql"
sql = migration.read_text()

conn = psycopg2.connect(conn_str)
conn.autocommit = True
cur = conn.cursor()
cur.execute(sql)
cur.close()
conn.close()

print("Migration applied.")
