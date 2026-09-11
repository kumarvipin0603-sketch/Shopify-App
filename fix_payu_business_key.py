from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import sys

target = Path("database.py")

if not target.exists():
    print("ERROR: database.py not found in the current folder.")
    sys.exit(1)

text = target.read_text(encoding="utf-8")

old_block = '''    elif source in [
        "PayU Settlement - Glen",
        "PayU Settlement - Alda",
    ]:
        payu_id = first_value(
            row,
            ["PayU ID"]
        )

        merchant_txn = first_value(
            row,
            ["Merchant Txn ID"]
        )

        key = "|".join(
            [
                normalize_key(payu_id),
                normalize_key(merchant_txn),
            ]
        )

        if key.replace("|", ""):
            return key
'''

new_block = '''    elif source in [
        "PayU Settlement - Glen",
        "PayU Settlement - Alda",
    ]:
        payu_id = first_value(
            row,
            ["PayU ID"]
        )

        merchant_txn = first_value(
            row,
            ["Merchant Txn ID"]
        )

        requested_action = first_value(
            row,
            ["Requested Action"]
        )

        key = "|".join(
            [
                normalize_key(payu_id),
                normalize_key(merchant_txn),
                normalize_key(requested_action),
            ]
        )

        if key.replace("|", ""):
            return key
'''

if old_block not in text:
    print("ERROR: Expected PayU business-key block was not found.")
    print("database.py was NOT changed.")
    sys.exit(2)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = Path(f"database_backup_payu_key_{stamp}.py")
shutil.copy2(target, backup)
print(f"Backup created: {backup}")

updated = text.replace(old_block, new_block, 1)
target.write_text(updated, encoding="utf-8")

try:
    py_compile.compile(str(target), doraise=True)
except Exception as e:
    shutil.copy2(backup, target)
    print("ERROR: Compile check failed. Original file restored.")
    print(e)
    sys.exit(3)

print("PayU business key updated successfully.")
print("New key: PayU ID | Merchant Txn ID | Requested Action")
print("database.py compile check: OK")
print()
print("Next:")
print("  1) Restart Streamlit")
print("  2) Re-upload PayU Settlement - Glen")
print("  3) Verify Failed = 0 (or only genuine unexpected conflicts remain)")
