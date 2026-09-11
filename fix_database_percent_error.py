from pathlib import Path
import shutil
from datetime import datetime
import py_compile
import sys

p = Path("database.py")
if not p.exists():
    print("ERROR: database.py not found in current folder.")
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = p.with_name(f"database_backup_percentfix_{stamp}.py")
shutil.copy2(p, backup)
print(f"Backup created: {backup.name}")

text = p.read_text(encoding="utf-8")

old = """WHERE business_key NOT LIKE 'sale-row:%'
                   OR business_key > %s"""
new = """WHERE business_key NOT LIKE 'sale-row:%%'
                   OR business_key > %s"""

if old not in text:
    if "NOT LIKE 'sale-row:%%'" in text:
        print("Percent fix already present.")
    else:
        print("ERROR: Expected SQL block not found. database.py was not changed.")
        sys.exit(2)
else:
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")
    print("Fixed psycopg2 percent escaping in Sale Register cleanup SQL.")

py_compile.compile(str(p), doraise=True)
print("database.py compile check: OK")
print()
print("Now run:")
print("py repair_sale_register_v2.py")
