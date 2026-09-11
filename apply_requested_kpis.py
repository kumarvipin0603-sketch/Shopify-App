from pathlib import Path
import re
import shutil
import sys
from datetime import datetime

BASE = Path(__file__).resolve().parent
APP = BASE / "app.py"
RECON = BASE / "reconciliation.py"

def backup(path: Path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = path.with_name(f"{path.stem}_backup_{stamp}{path.suffix}")
    shutil.copy2(path, dst)
    return dst

def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)

if not APP.exists():
    fail(f"{APP.name} not found in {BASE}")

if not RECON.exists():
    fail(f"{RECON.name} not found in {BASE}")

app_backup = backup(APP)
recon_backup = backup(RECON)

print(f"Backup created: {app_backup.name}")
print(f"Backup created: {recon_backup.name}")

# ============================================================
# PATCH reconciliation.py
# ============================================================

text = RECON.read_text(encoding="utf-8")

if "from reconciliation import (" in text:
    fail(
        "reconciliation.py contains a circular self-import. "
        "Restore the working reconciliation.py first."
    )

old = 'for c in ["Total","Refunded Amount","Outstanding Balance","Qty"]:'
new = 'for c in ["Subtotal","Total","Refunded Amount","Outstanding Balance","Qty"]:'
if old in text:
    text = text.replace(old, new, 1)
elif '"Subtotal","Total","Refunded Amount","Outstanding Balance","Qty"' not in text:
    print("WARNING: Could not find Shopify numeric-field line automatically.")

old = '"Total":"max", "Refunded Amount":"max", "Outstanding Balance":"max",'
new = '"Subtotal":"max", "Total":"max", "Refunded Amount":"max", "Outstanding Balance":"max",'
if old in text:
    text = text.replace(old, new, 1)
elif '"Subtotal":"max"' not in text:
    print("WARNING: Could not find aggregate_shopify Total aggregation automatically.")

new_aggregate_sales = '''def aggregate_sales(df):
    if df.empty:
        return pd.DataFrame(columns=[
            "Order No",
            "Invoice_No",
            "Invoice_Date",
            "Invoice_Value",
            "Invoice_Qty",
            "CN_No",
            "CN_Date",
            "CN_Value",
        ])

    df = df.copy()

    if "Document Type" in df.columns:
        doc_type = (
            df["Document Type"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
        )
        inv = df[doc_type.eq("invoice")].copy()
        credits = df[
            doc_type.str.contains(
                "credit|return|cn",
                regex=True,
                na=False,
            )
        ].copy()
    else:
        inv = df.copy()
        credits = pd.DataFrame(columns=df.columns)

    all_orders = df[["Order No"]].drop_duplicates().copy()
    out = all_orders.copy()

    if not inv.empty:
        g = inv.groupby("Order No")

        if "Gross Amount" in inv.columns:
            s = g["Gross Amount"].sum().rename("Invoice_Value")
            out = out.merge(s, on="Order No", how="left")

        if "Quantity" in inv.columns:
            s = g["Quantity"].sum().rename("Invoice_Qty")
            out = out.merge(s, on="Order No", how="left")

        if "Invoice Date" in inv.columns:
            s = g["Invoice Date"].max().rename("Invoice_Date")
            out = out.merge(s, on="Order No", how="left")

        if "Invoice No" in inv.columns:
            s = g["Invoice No"].apply(
                lambda x: ", ".join(
                    dict.fromkeys(
                        clean_str(v)
                        for v in x
                        if clean_str(v)
                    )
                )
            ).rename("Invoice_No")
            out = out.merge(s, on="Order No", how="left")

    if not credits.empty:
        cg = credits.groupby("Order No")

        if "Gross Amount" in credits.columns:
            s = cg["Gross Amount"].sum().abs().rename("CN_Value")
            out = out.merge(s, on="Order No", how="left")

        if "Invoice No" in credits.columns:
            s = cg["Invoice No"].apply(
                lambda x: ", ".join(
                    dict.fromkeys(
                        clean_str(v)
                        for v in x
                        if clean_str(v)
                    )
                )
            ).rename("CN_No")
            out = out.merge(s, on="Order No", how="left")

        if "Invoice Date" in credits.columns:
            s = cg["Invoice Date"].max().rename("CN_Date")
            out = out.merge(s, on="Order No", how="left")

    defaults = {
        "Invoice_No": "",
        "Invoice_Date": pd.NaT,
        "Invoice_Value": 0,
        "Invoice_Qty": 0,
        "CN_No": "",
        "CN_Date": pd.NaT,
        "CN_Value": 0,
    }

    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    for col in ["Invoice_Value", "Invoice_Qty", "CN_Value"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)

    for col in ["Invoice_No", "CN_No"]:
        out[col] = out[col].fillna("").astype(str)
        out[col] = out[col].replace({"nan": "", "None": ""})

    return out
'''

pattern = re.compile(
    r"def aggregate_sales\\(df\\):.*?(?=\\ndef _match_by_payment\\()",
    re.S,
)

if pattern.search(text):
    text = pattern.sub(new_aggregate_sales.rstrip() + "\\n\\n", text, count=1)
else:
    fail("Could not locate aggregate_sales() in reconciliation.py.")

cols_pattern = re.compile(
    r'    cols=\\["Order No","Created at".*?\\]\\n    cols=\\[c for c in cols if c in ct\\.columns\\]',
    re.S,
)

new_cols = '''    cols=[
        "Order No",
        "Created at",
        "Billing Name",
        "Email",
        "Subtotal",
        "Total",
        "Order Qty",
        "SKUs",
        "Payment Method",
        "Financial Status",
        "Order Status",
        "Fulfilment Status",
        "Billing Status",
        "Invoice_No",
        "Invoice_Date",
        "Invoice_Value",
        "CN Status",
        "CN_No",
        "CN_Date",
        "CN_Value",
        "Payment Status",
        "Matched_Gateway",
        "Gateway_Collection",
        "Gateway_Refund",
        "Gateway_Settlement",
        "Settlement Status",
        "Last_Settlement_Date",
        "Settlement_UTR",
        "Settlement Difference",
        "Refund Status",
        "Refunded Amount",
        "Outstanding Balance",
        "Final Closure",
        "Exception Reason",
        "Match_Method",
        "Products",
    ]
    cols=[c for c in cols if c in ct.columns]'''

if cols_pattern.search(text):
    text = cols_pattern.sub(new_cols, text, count=1)
elif '"CN_No"' not in text or '"CN_Date"' not in text or '"Subtotal"' not in text:
    fail("Could not update final control-tower column order.")

RECON.write_text(text, encoding="utf-8")
print("Updated reconciliation.py")

# ============================================================
# PATCH app.py
# ============================================================

app = APP.read_text(encoding="utf-8")

if "def show_selected_date_kpis(" not in app:
    kpi_block = '''

# =========================================================
# GLOBAL SELECTED-DATE KPI STRIP
# Based on selected Shopify Created-at / Order Date range.
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
        order_billed_count = int(
            df["Billing Status"].eq("Billed").sum()
        )
        order_not_billed_count = int(
            (~df["Billing Status"].eq("Billed")).sum()
        )
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
    show_selected_date_kpis(
        ct,
        date_filter_label,
    )
'''

    candidates = [
        "ct,matches,date_filter_label=apply_global_date_filter(ct,matches)",
        "ct, matches, date_filter_label = apply_global_date_filter(ct, matches)",
        "ct,matches,date_filter_label = apply_global_date_filter(ct,matches)",
    ]

    inserted = False
    for marker in candidates:
        if marker in app:
            app = app.replace(marker, marker + kpi_block, 1)
            inserted = True
            break

    if not inserted:
        rx = re.compile(
            r"(ct\\s*,\\s*matches\\s*,\\s*date_filter_label\\s*=\\s*"
            r"apply_global_date_filter\\(\\s*ct\\s*,\\s*matches\\s*\\))"
        )
        m = rx.search(app)
        if m:
            pos = m.end()
            app = app[:pos] + kpi_block + app[pos:]
            inserted = True

    if not inserted:
        fail("Could not locate the global date-filter result line in app.py.")

app = app.replace(
    "Search order / invoice / customer / SKU",
    "Search order / invoice / CN / customer / SKU",
)

APP.write_text(app, encoding="utf-8")
print("Updated app.py")

print()
print("PATCH COMPLETE")
print("Now run:")
print("  py -m py_compile reconciliation.py")
print("  py -m py_compile app.py")
print("  py -m streamlit run app.py")
