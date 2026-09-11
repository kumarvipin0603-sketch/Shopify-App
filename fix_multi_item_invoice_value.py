from pathlib import Path
import shutil
import sys
from datetime import datetime

BASE = Path(__file__).resolve().parent
RECON = BASE / "reconciliation.py"

def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)

if not RECON.exists():
    fail(f"{RECON.name} not found in {BASE}")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = RECON.with_name(f"reconciliation_backup_{stamp}.py")
shutil.copy2(RECON, backup)
print(f"Backup created: {backup.name}")

text = RECON.read_text(encoding="utf-8")

start_marker = "def load_sales(data_dir):"
end_marker = "\ndef aggregate_sales("
start = text.find(start_marker)
end = text.find(end_marker, start)

if start == -1 or end == -1:
    fail("Could not locate load_sales() block in reconciliation.py.")

new_load_sales = '''def load_sales(data_dir):
    path = source_path(data_dir, "Sale Register")
    if not path.exists():
        return pd.DataFrame()

    xl = pd.ExcelFile(path)
    sheet = "MSD" if "MSD" in xl.sheet_names else xl.sheet_names[-1]
    df = read_excel(path, sheet_name=sheet)

    if "Po Number" not in df.columns:
        return pd.DataFrame()

    # Multi-item invoices often repeat header values only on the first row.
    # Fill those header fields down so every item row stays linked to the
    # correct Shopify order and invoice before aggregation.
    header_cols = [
        "Po Number",
        "Invoice No",
        "Invoice Date",
        "Document Type",
    ]
    for c in header_cols:
        if c in df.columns:
            df[c] = df[c].ffill()

    df["Order No"] = df["Po Number"].map(norm_order)

    for c in ["Gross Amount", "Quantity"]:
        if c in df.columns:
            df[c] = num(df[c])

    if "Invoice Date" in df.columns:
        df["Invoice Date"] = pd.to_datetime(
            df["Invoice Date"],
            errors="coerce",
        )

    df = df[df["Order No"].astype(str).str.strip().ne("")].copy()

    return df

'''

text = text[:start] + new_load_sales + text[end:]
RECON.write_text(text, encoding="utf-8")

print("Updated reconciliation.py")
print()
print("FIX APPLIED:")
print("- Multi-item rows inherit Po Number / Invoice No / Invoice Date / Document Type.")
print("- Invoice_Value will sum Gross Amount across all item rows for the order.")
print("- Invoice_Qty will sum Quantity across all item rows.")
print("- Existing CN logic is preserved.")
print()
print("Run next:")
print("  py -m py_compile reconciliation.py")
print("  py -m streamlit run app.py")
