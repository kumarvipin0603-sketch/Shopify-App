from pathlib import Path
import json
import pandas as pd
import importlib.util

BASE = Path(__file__).resolve().parent
DBFILE = BASE / "database.py"
SALEFILE = BASE / "data" / "sale_register.xlsx"

print("\n=== 1) LOCAL SALE REGISTER ===")
if SALEFILE.exists():
    x = pd.ExcelFile(SALEFILE)
    sheet = "MSD" if "MSD" in x.sheet_names else x.sheet_names[-1]
    d = pd.read_excel(SALEFILE, sheet_name=sheet)
    mask = (
        d.get("Po Number", pd.Series("", index=d.index)).astype(str).str.strip().eq("#69316")
        | d.get("Invoice No", pd.Series("", index=d.index)).astype(str).str.strip().eq("SI262716-006830")
    )
    cols = [c for c in ["Po Number","Invoice No","Invoice Date","Product/Item No","Quantity","Gross Amount","Document Type"] if c in d.columns]
    print(d.loc[mask, cols].to_string(index=True))
    if "Gross Amount" in d.columns and "Document Type" in d.columns:
        m = d.loc[mask].copy()
        inv = m["Document Type"].astype(str).str.strip().str.lower().eq("invoice")
        print("LOCAL INVOICE SUM =", pd.to_numeric(m.loc[inv, "Gross Amount"], errors="coerce").fillna(0).sum())
else:
    print("Local file not found:", SALEFILE)

print("\n=== 2) DATABASE.PY ===")
if not DBFILE.exists():
    raise SystemExit("database.py not found")

spec = importlib.util.spec_from_file_location("dbmod", DBFILE)
db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)

print("Has make_business_key:", hasattr(db, "make_business_key"))
print("Has get_connection:", hasattr(db, "get_connection"))

print("\n=== 3) DATABASE TABLE COLUMNS ===")
conn = db.get_connection()
cur = conn.cursor()
cur.execute("""
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'sale_register_raw'
ORDER BY ordinal_position
""")
columns = cur.fetchall()
for c in columns:
    print(c)

colnames = [c[0] for c in columns]
print("\nColumns:", colnames)

print("\n=== 4) DATABASE ROWS FOR #69316 / SI262716-006830 ===")
# Build a generic text search across every column, cast to text.
where = " OR ".join([f'CAST("{c}" AS TEXT) ILIKE %s' for c in colnames])
sql = f'SELECT * FROM sale_register_raw WHERE {where}'
params = []
for _ in colnames:
    params.append("%69316%")
cur.execute(sql, params)
rows1 = cur.fetchall()

params2 = []
for _ in colnames:
    params2.append("%SI262716-006830%")
cur.execute(sql, params2)
rows2 = cur.fetchall()

# de-duplicate result tuples
seen = set()
rows = []
for r in rows1 + rows2:
    key = repr(r)
    if key not in seen:
        seen.add(key)
        rows.append(r)

print("MATCHING DB ROW COUNT =", len(rows))
for i, row in enumerate(rows, 1):
    print(f"\n--- DB ROW {i} ---")
    rec = dict(zip(colnames, row))
    for k, v in rec.items():
        if isinstance(v, dict):
            print(k, "=", json.dumps(v, ensure_ascii=False, default=str))
        else:
            print(k, "=", v)

cur.close()
conn.close()

print("\n=== RESULT GUIDE ===")
print("If LOCAL shows 2 rows / 9998.99 but DB shows only 1 row, ingestion/UPSERT is still dropping a line.")
print("If DB shows 2 rows but dashboard still shows 4489.99, the bug is in database read/reconciliation aggregation.")
