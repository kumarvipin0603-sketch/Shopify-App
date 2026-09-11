from pathlib import Path
import ast
import shutil
import sys
from datetime import datetime

BASE = Path(__file__).resolve().parent
DBFILE = BASE / "database.py"

def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)

if not DBFILE.exists():
    fail(f"{DBFILE.name} not found in {BASE}")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = DBFILE.with_name(f"database_backup_{stamp}.py")
shutil.copy2(DBFILE, backup)
print(f"Backup created: {backup.name}")

text = DBFILE.read_text(encoding="utf-8")

patch_marker = "# SALE_REGISTER_MULTI_ITEM_KEY_FIX_V1"

if patch_marker not in text:
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        fail(f"database.py has a syntax error before patching: {e}")

    target = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "make_business_key":
            target = node
            break

    if target is None:
        fail("Could not find make_business_key() in database.py.")

    lines = text.splitlines(keepends=True)
    insert_at = target.end_lineno

    wrapper = '''
# SALE_REGISTER_MULTI_ITEM_KEY_FIX_V1
# Preserve every genuine line item of the same Shopify order/invoice.
# Sale Register key must be line-item specific.
_make_business_key_before_sale_register_fix = make_business_key

def make_business_key(*args, **kwargs):
    source = kwargs.get("source")
    row = kwargs.get("row")

    if source is None and len(args) >= 1:
        source = args[0]
    if row is None and len(args) >= 2:
        row = args[1]

    if source == "Sale Register" and row is not None:
        def _v(name):
            try:
                value = row.get(name, "")
            except Exception:
                try:
                    value = row[name]
                except Exception:
                    value = ""
            if value is None:
                return ""
            value = str(value).strip()
            if value.lower() in {"nan", "none", "nat"}:
                return ""
            return value

        parts = [
            _v("Po Number"),
            _v("Invoice No"),
            _v("Product/Item No"),
            _v("Document Type"),
        ]
        return "SALE|" + "|".join(parts)

    return _make_business_key_before_sale_register_fix(*args, **kwargs)

'''
    lines.insert(insert_at, wrapper)
    text = "".join(lines)
    DBFILE.write_text(text, encoding="utf-8")
    print("Patched database.py business key logic.")
else:
    print("database.py already contains the Sale Register multi-item key fix.")

try:
    compile(DBFILE.read_text(encoding="utf-8"), str(DBFILE), "exec")
except SyntaxError as e:
    shutil.copy2(backup, DBFILE)
    fail(f"Patched database.py did not compile. Original restored. Error: {e}")

print("database.py compile check: OK")

try:
    import importlib.util

    spec = importlib.util.spec_from_file_location("database_fixed", DBFILE)
    db = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db)

    if not hasattr(db, "get_connection"):
        fail("database.py does not expose get_connection(); no database rows were deleted.")

    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM sale_register_raw")
    deleted = cur.rowcount

    try:
        cur.execute(
            "DELETE FROM upload_history WHERE source_name = %s",
            ("Sale Register",),
        )
    except Exception:
        conn.rollback()
        cur = conn.cursor()
        cur.execute("DELETE FROM sale_register_raw")
        deleted = cur.rowcount

    conn.commit()
    cur.close()
    conn.close()

    print(f"Sale Register database reset complete. Deleted rows: {deleted}")

except Exception as e:
    print()
    print("WARNING: database.py was patched successfully, but automatic Sale Register reset failed.")
    print(f"Reason: {e}")
    print("No other source tables were touched.")
    sys.exit(2)

print()
print("FIX COMPLETE")
print("NEXT:")
print("Open Streamlit -> Upload Centre -> Sale Register")
print("Upload the full current Sale Register Excel again.")
print()
print("Expected for #69316:")
print("SI262716-006830 = 5509.00 + 4489.99 = 9998.99")
