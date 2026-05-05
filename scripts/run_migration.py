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

migrations_dir = Path(__file__).parent.parent / "supabase" / "migrations"
files = sorted(migrations_dir.glob("*.sql"))

if not files:
    print("No migration files found.")
    sys.exit(0)

conn = psycopg2.connect(conn_str)
conn.autocommit = True
cur = conn.cursor()

for f in files:
    sql = f.read_text()
    try:
        cur.execute(sql)
        print(f"OK  {f.name}")
    except Exception as e:
        print(f"ERR {f.name}: {e}")

cur.close()
conn.close()
print("\nAll migrations processed.")
