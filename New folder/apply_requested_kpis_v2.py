from pathlib import Path
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

print(f"Backup created: {backup(APP).name}")
print(f"Backup created: {backup(RECON).name}")

text = RECON.read_text(encoding="utf-8")

if "from reconciliation import (" in text:
    fail("reconciliation.py contains a circular self-import.")

text = text.replace(
    'for c in ["Total","Refunded Amount","Outstanding Balance","Qty"]:',
    'for c in ["Subtotal","Total","Refunded Amount","Outstanding Balance","Qty"]:',
    1,
)

text = text.replace(
    '"Total":"max", "Refunded Amount":"max", "Outstanding Balance":"max",',
    '"Subtotal":"max", "Total":"max", "Refunded Amount":"max", "Outstanding Balance":"max",',
    1,
)

start_marker = "def aggregate_sales(df):"
end_marker = "\ndef _match_by_payment("
start = text.find(start_marker)
end = text.find(end_marker, start)
if start == -1 or end == -1:
    fail("Could not locate aggregate_sales() block.")

new_aggregate_sales = """def aggregate_sales(df):
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

    out = df[["Order No"]].drop_duplicates().copy()

    if not inv.empty:
        g = inv.groupby("Order No")

        if "Gross Amount" in inv.columns:
            out = out.merge(
                g["Gross Amount"].sum().rename("Invoice_Value"),
                on="Order No",
                how="left",
            )

        if "Quantity" in inv.columns:
            out = out.merge(
                g["Quantity"].sum().rename("Invoice_Qty"),
                on="Order No",
                how="left",
            )

        if "Invoice Date" in inv.columns:
            out = out.merge(
                g["Invoice Date"].max().rename("Invoice_Date"),
                on="Order No",
                how="left",
            )

        if "Invoice No" in inv.columns:
            invnos = g["Invoice No"].apply(
                lambda x: ", ".join(
                    dict.fromkeys(
                        clean_str(v)
                        for v in x
                        if clean_str(v)
                    )
                )
            ).rename("Invoice_No")
            out = out.merge(invnos, on="Order No", how="left")

    if not credits.empty:
        cg = credits.groupby("Order No")

        if "Gross Amount" in credits.columns:
            out = out.merge(
                cg["Gross Amount"].sum().abs().rename("CN_Value"),
                on="Order No",
                how="left",
            )

        if "Invoice No" in credits.columns:
            cn_nos = cg["Invoice No"].apply(
                lambda x: ", ".join(
                    dict.fromkeys(
                        clean_str(v)
                        for v in x
                        if clean_str(v)
                    )
                )
            ).rename("CN_No")
            out = out.merge(cn_nos, on="Order No", how="left")

        if "Invoice Date" in credits.columns:
            out = out.merge(
                cg["Invoice Date"].max().rename("CN_Date"),
                on="Order No",
                how="left",
            )

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

"""

text = text[:start] + new_aggregate_sales + text[end:]

cols_start_marker = '    cols=["Order No","Created at"'
cols_end_marker = '    cols=[c for c in cols if c in ct.columns]'
cols_start = text.find(cols_start_marker)
cols_end = text.find(cols_end_marker, cols_start)
if cols_start == -1 or cols_end == -1:
    fail("Could not locate final control-tower column list.")
cols_end += len(cols_end_marker)

new_cols = """    cols=[
        "Order No","Created at","Billing Name","Email","Subtotal","Total",
        "Order Qty","SKUs","Payment Method","Financial Status",
        "Order Status","Fulfilment Status","Billing Status",
        "Invoice_No","Invoice_Date","Invoice_Value",
        "CN Status","CN_No","CN_Date","CN_Value",
        "Payment Status","Matched_Gateway","Gateway_Collection",
        "Gateway_Refund","Gateway_Settlement","Settlement Status",
        "Last_Settlement_Date","Settlement_UTR","Settlement Difference",
        "Refund Status","Refunded Amount","Outstanding Balance",
        "Final Closure","Exception Reason","Match_Method","Products"
    ]
    cols=[c for c in cols if c in ct.columns]"""

text = text[:cols_start] + new_cols + text[cols_end:]
RECON.write_text(text, encoding="utf-8")
print("Updated reconciliation.py")

app = APP.read_text(encoding="utf-8")

if "def show_selected_date_kpis(" not in app:
    marker = "ct,matches,date_filter_label=apply_global_date_filter(ct,matches)"
    if marker not in app:
        fail("Could not locate selected-date filter result line in app.py.")

    kpi_block = """

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
"""

    app = app.replace(marker, marker + kpi_block, 1)

app = app.replace(
    "Search order / invoice / customer / SKU",
    "Search order / invoice / CN / customer / SKU",
)

APP.write_text(app, encoding="utf-8")
print("Updated app.py")

print()
print("PATCH COMPLETE")
print("Next run:")
print("py -m py_compile reconciliation.py")
print("py -m py_compile app.py")
print("py -m streamlit run app.py")
