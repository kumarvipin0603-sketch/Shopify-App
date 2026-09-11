from pathlib import Path
import pandas as pd

from database import upsert_dataframe, read_source_from_database

BASE = Path(__file__).resolve().parent
SALE_FILE = BASE / "data" / "sale_register.xlsx"

print("=" * 72)
print("SALE REGISTER ROW-PRESERVING DATABASE REPAIR")
print("=" * 72)

if not SALE_FILE.exists():
    raise SystemExit(f"ERROR: {SALE_FILE} not found")

xls = pd.ExcelFile(SALE_FILE)
sheet = "MSD" if "MSD" in xls.sheet_names else xls.sheet_names[-1]
df = pd.read_excel(xls, sheet_name=sheet)

print(f"Local Sale Register rows: {len(df):,}")

required = ["Po Number", "Invoice No", "Product/Item No", "Gross Amount", "Document Type"]
missing = [c for c in required if c not in df.columns]
if missing:
    raise SystemExit(f"ERROR: Missing columns: {missing}")

m = df["Po Number"].astype(str).str.strip().eq("#69316")
inv = m & df["Document Type"].astype(str).str.strip().str.lower().eq("invoice")

print("\nLOCAL #69316:")
print(df.loc[m, required].to_string(index=False))

local_sum = pd.to_numeric(
    df.loc[inv, "Gross Amount"],
    errors="coerce"
).fillna(0).sum()

print(f"Local #69316 invoice rows: {int(inv.sum())}")
print(f"Local #69316 invoice sum : {local_sum:.2f}")

if int(inv.sum()) < 2 or round(float(local_sum), 2) != 9998.99:
    raise SystemExit(
        "ERROR: This local Sale Register is not the full/correct source. "
        "Database was NOT changed."
    )

print("\nWriting the COMPLETE Sale Register snapshot to Neon...")
result = upsert_dataframe(
    "Sale Register",
    df,
    file_name=SALE_FILE.name,
)
print("Database result:", result)

db = read_source_from_database("Sale Register")
print(f"Neon Sale Register rows: {len(db):,}")

dm = db["Po Number"].astype(str).str.strip().eq("#69316")
dinv = dm & db["Document Type"].astype(str).str.strip().str.lower().eq("invoice")

print("\nNEON #69316:")
print(db.loc[dm, [c for c in required if c in db.columns]].to_string(index=False))

db_sum = pd.to_numeric(
    db.loc[dinv, "Gross Amount"],
    errors="coerce"
).fillna(0).sum()

print(f"Neon #69316 invoice rows: {int(dinv.sum())}")
print(f"Neon #69316 invoice sum : {db_sum:.2f}")

if len(db) != len(df):
    raise SystemExit(
        f"ERROR: Row count still differs: local={len(df):,}, Neon={len(db):,}"
    )

if int(dinv.sum()) < 2 or round(float(db_sum), 2) != 9998.99:
    raise SystemExit("ERROR: #69316 verification failed after database write.")

print("\nSUCCESS")
print("Sale Register is now preserved row-for-row in Neon.")
print("#69316 invoice value = 9998.99")
print("Now run: py -m streamlit run app.py")
