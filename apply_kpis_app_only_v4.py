from pathlib import Path
import shutil
import sys
from datetime import datetime

BASE = Path(__file__).resolve().parent
APP = BASE / "app.py"

def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)

if not APP.exists():
    fail(f"{APP.name} not found in {BASE}")

app = APP.read_text(encoding="utf-8")

if "def show_selected_date_kpis(" in app:
    print("KPI block already exists in app.py. Nothing to change.")
    sys.exit(0)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = APP.with_name(f"app_backup_{stamp}.py")
shutil.copy2(APP, backup)
print(f"Backup created: {backup.name}")

lines = app.splitlines(keepends=True)

# Locate the multiline assignment that starts with:
# ct, matches, date_filter_label = (
start = None
for i, line in enumerate(lines):
    compact = line.replace(" ", "").replace("\t", "")
    if "ct,matches,date_filter_label=(" in compact:
        start = i
        break

if start is None:
    fail("Could not locate ct, matches, date_filter_label assignment.")

# Find the end of the parenthesized assignment using simple bracket balance.
balance = 0
seen_open = False
end = None
for i in range(start, len(lines)):
    line = lines[i]
    balance += line.count('(')
    if line.count('('):
        seen_open = True
    balance -= line.count(')')
    if seen_open and balance == 0:
        end = i
        break

if end is None:
    fail("Could not determine end of date-filter assignment.")

print(f"Found date-filter block at lines {start+1}-{end+1}.")

kpi_block = '''

# =========================================================
# GLOBAL SELECTED-DATE KPI STRIP
# =========================================================

def _kpi_sum(df, column):
    if df.empty or column not in df.columns:
        return 0.0
    return pd.to_numeric(df[column], errors="coerce").fillna(0).sum()


def _format_inr_kpi(value):
    value = float(value or 0)
    absolute = abs(value)
    if absolute >= 10_000_000:
        return f"₹{value / 10_000_000:,.2f} Cr"
    if absolute >= 100_000:
        return f"₹{value / 100_000:,.2f} L"
    return f"₹{value:,.0f}"


def show_selected_date_kpis(df, selected_date_label):
    if df.empty:
        return

    order_count = len(df)
    order_subtotal_value = _kpi_sum(df, "Subtotal")
    invoice_value = _kpi_sum(df, "Invoice_Value")
    cn_value = _kpi_sum(df, "CN_Value")

    if "Billing Status" in df.columns:
        order_billed_count = int(df["Billing Status"].eq("Billed").sum())
        order_not_billed_count = int((~df["Billing Status"].eq("Billed")).sum())
    else:
        order_billed_count = 0
        order_not_billed_count = order_count

    st.caption(f"Shopify Order Date: {selected_date_label}")

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Order Count", f"{order_count:,}")
    k2.metric("Order Subtotal Value", _format_inr_kpi(order_subtotal_value))
    k3.metric("Invoice Value", _format_inr_kpi(invoice_value))
    k4.metric("CN Value", _format_inr_kpi(cn_value))
    k5.metric("Order Billed Count", f"{order_billed_count:,}")
    k6.metric("Order Not Billed Count", f"{order_not_billed_count:,}")

    st.divider()


if not ct.empty:
    show_selected_date_kpis(ct, date_filter_label)

'''

lines.insert(end + 1, kpi_block)
app = "".join(lines)

app = app.replace(
    "Search order / invoice / customer / SKU",
    "Search order / invoice / CN / customer / SKU",
)

APP.write_text(app, encoding="utf-8")
print("Updated app.py")
print("PATCH COMPLETE")
print()
print("Run next:")
print("  py -m py_compile app.py")
print("  py -m py_compile reconciliation.py")
print("  py -m streamlit run app.py")