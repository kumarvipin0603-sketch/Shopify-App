from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import sys
import importlib
import pandas as pd

TARGET = Path("database.py")
PAYU_FILE = Path(r"data\payu_glen.xlsx")
SOURCE = "PayU Settlement - Glen"
TABLE = "payu_glen_raw"

if not TARGET.exists():
    print("ERROR: database.py not found in current folder.")
    sys.exit(1)

if not PAYU_FILE.exists():
    print(r"ERROR: data\payu_glen.xlsx not found.")
    sys.exit(2)

text = TARGET.read_text(encoding="utf-8")

old_ts = '''    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if isinstance(value, datetime):
        return value.isoformat()
'''

new_ts = '''    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")

    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
'''

if old_ts in text:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = Path(f"database_backup_payu_datetime_{stamp}.py")
    shutil.copy2(TARGET, backup)
    print(f"Backup created: {backup}")
    text = text.replace(old_ts, new_ts, 1)
    TARGET.write_text(text, encoding="utf-8")
elif 'return value.isoformat(sep=" ")' in text:
    print("Datetime normalization patch is already present.")
else:
    print("ERROR: Expected clean_value datetime block not found.")
    print("database.py was not changed.")
    sys.exit(3)

try:
    py_compile.compile(str(TARGET), doraise=True)
except Exception as e:
    print("ERROR: database.py compile check failed.")
    print(e)
    sys.exit(4)

print("database.py compile check: OK")
print("Datetime values now normalize with a SPACE separator.")

import database
importlib.reload(database)

df = pd.read_excel(PAYU_FILE)
df = database.prepare_dataframe(df)

prepared = {}
exact_dupes = 0
conflicts = []

for idx, row in df.iterrows():
    row_dict = {
        str(col): database.clean_value(value)
        for col, value in row.items()
    }
    key = database.make_business_key(SOURCE, row_dict)
    h = database.row_hash(row_dict)

    if key in prepared:
        prev = prepared[key]
        if prev["hash"] == h:
            exact_dupes += 1
            continue

        diffs = []
        for col in sorted(set(prev["row"]) | set(row_dict)):
            if prev["row"].get(col) != row_dict.get(col):
                diffs.append((col, prev["row"].get(col), row_dict.get(col)))

        conflicts.append((idx, key, diffs))

    prepared[key] = {"hash": h, "row": row_dict}

print()
print("=" * 78)
print("LOCAL PAYU VALIDATION")
print("=" * 78)
print(f"Rows in file          : {len(df)}")
print(f"Exact duplicates      : {exact_dupes}")
print(f"Conflicting duplicates: {len(conflicts)}")
print(f"Unique business keys  : {len(prepared)}")

if conflicts:
    print()
    print("STOPPED: Conflicting duplicates still remain.")
    for idx, key, diffs in conflicts[:20]:
        print(f"idx={idx} key={key}")
        for col, old, new in diffs:
            print(f"  {col}: {old!r} -> {new!r}")
    sys.exit(5)

print()
print("Uploading corrected PayU keys to Neon...")
result = database.upsert_dataframe(
    SOURCE,
    df,
    file_name=PAYU_FILE.name,
)
print("Upsert result:", result)

conn = database.get_connection()
try:
    cur = conn.cursor()
    cur.execute(f"SELECT business_key FROM {TABLE}")
    keys = [r[0] for r in cur.fetchall()]

    legacy_keys = [
        k for k in keys
        if isinstance(k, str) and k.count("|") < 2
    ]

    if legacy_keys:
        cur.execute(
            f"DELETE FROM {TABLE} WHERE business_key = ANY(%s)",
            (legacy_keys,),
        )
        deleted = cur.rowcount
    else:
        deleted = 0

    conn.commit()
finally:
    conn.close()

print(f"Legacy old-key rows removed from Neon: {deleted}")

persisted = database.read_source_from_database(SOURCE)
print(f"Neon PayU Glen rows after cleanup: {len(persisted):,}")

expected_unique = len(prepared)

if len(persisted) != expected_unique:
    print()
    print("WARNING:")
    print(f"Expected {expected_unique:,} unique rows but Neon has {len(persisted):,}.")
    print("Do not upload again yet. Send this complete output for review.")
    sys.exit(6)

print()
print("=" * 78)
print("SUCCESS")
print("=" * 78)
print(f"PayU Glen is clean in Neon: {len(persisted):,} unique rows.")
print(f"True duplicate rows skipped: {exact_dupes}")
print("Conflicting duplicate rows: 0")
print()
print("Now restart Streamlit:")
print("  py -m streamlit run app.py")
