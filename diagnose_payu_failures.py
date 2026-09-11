import pandas as pd
import database

FILE = r"data\payu_glen.xlsx"
SOURCE = "PayU Settlement - Glen"

df = pd.read_excel(FILE)
df = database.prepare_dataframe(df)

prepared = {}
same_hash = []
different_hash = []

for idx, row in df.iterrows():
    row_dict = {
        str(col): database.clean_value(value)
        for col, value in row.items()
    }

    key = database.make_business_key(SOURCE, row_dict)
    h = database.row_hash(row_dict)

    if key in prepared:
        prev = prepared[key]
        item = {
            "excel_row_index": int(idx),
            "business_key": key,
            "previous_index": prev["idx"],
            "requested_action": row_dict.get("Requested Action"),
            "payu_id": row_dict.get("PayU ID"),
            "merchant_txn_id": row_dict.get("Merchant Txn ID"),
        }

        if prev["hash"] == h:
            same_hash.append(item)
        else:
            # capture field-level differences
            diffs = []
            all_cols = sorted(set(prev["row"].keys()) | set(row_dict.keys()))
            for c in all_cols:
                a = prev["row"].get(c)
                b = row_dict.get(c)
                if a != b:
                    diffs.append((c, a, b))
            item["differences"] = diffs
            different_hash.append(item)

    prepared[key] = {
        "idx": int(idx),
        "hash": h,
        "row": row_dict,
    }

print("=" * 90)
print("PAYU DUPLICATE CLASSIFICATION USING DATABASE.PY LOGIC")
print("=" * 90)
print(f"Rows in file                 : {len(df)}")
print(f"Exact duplicate rows -> Skip : {len(same_hash)}")
print(f"Conflicting duplicate rows   : {len(different_hash)}")
print()

if same_hash:
    print("EXACT DUPLICATES (should be SKIPPED)")
    print("-" * 90)
    for x in same_hash:
        print(
            f"idx={x['excel_row_index']} prev={x['previous_index']} "
            f"PayU ID={x['payu_id']} Action={x['requested_action']} "
            f"Merchant Txn ID={x['merchant_txn_id']}"
        )
    print()

if different_hash:
    print("CONFLICTING DUPLICATES (currently counted as FAILED)")
    print("-" * 90)
    for x in different_hash:
        print(
            f"idx={x['excel_row_index']} prev={x['previous_index']} "
            f"PayU ID={x['payu_id']} Action={x['requested_action']} "
            f"Merchant Txn ID={x['merchant_txn_id']}"
        )
        for col, old, new in x["differences"]:
            print(f"   {col}: {old!r}  ->  {new!r}")
        print()
else:
    print("No conflicting duplicates found.")

print("=" * 90)
