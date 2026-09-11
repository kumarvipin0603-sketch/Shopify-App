from pathlib import Path
import io
import re

import pandas as pd
import streamlit as st

from reconciliation import (
    SOURCE_FILES,
    available_sources,
    build_control_tower,
    source_path,
)

from database import (
    create_database_tables,
    upsert_dataframe,
    read_source_from_database,
    get_database_counts,
    get_upload_history,
)


BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)


st.set_page_config(
    page_title="Website Order Control Tower",
    page_icon="📦",
    layout="wide",
)


st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
    }

    .stMetric {
        border: 1px solid #e7e7e7;
        border-radius: 10px;
        padding: 12px;
        background: white;
    }

    .small-note {
        color: #666;
        font-size: .88rem;
    }

    .status-ok {
        color: #16794b;
    }

    .status-warn {
        color: #b36b00;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def save_local_source(source, df):
    """
    Creates the temporary/local Excel copy used by the
    existing reconciliation engine.

    Permanent data remains in Neon PostgreSQL.
    """

    target = source_path(DATA, source)

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if source == "Sale Register":
        with pd.ExcelWriter(
            target,
            engine="openpyxl",
        ) as writer:
            df.to_excel(
                writer,
                index=False,
                sheet_name="MSD",
            )

    elif source == "Mobikwik":
        with pd.ExcelWriter(
            target,
            engine="openpyxl",
        ) as writer:
            df.to_excel(
                writer,
                index=False,
                sheet_name="Report",
            )

    else:
        with pd.ExcelWriter(
            target,
            engine="openpyxl",
        ) as writer:
            df.to_excel(
                writer,
                index=False,
                sheet_name="Sheet1",
            )


def sync_database_to_local():
    """
    Restores the application's temporary source files
    from permanent Neon storage.

    This is what allows the deployed app to recover after
    a restart even though Streamlit's local disk is temporary.
    """

    create_database_tables()

    restored = 0

    for source in SOURCE_FILES:
        df = read_source_from_database(
            source
        )

        if not df.empty:
            save_local_source(
                source,
                df,
            )

            restored += 1

    return restored


def read_uploaded_source(source, uploaded_file):
    name = uploaded_file.name.lower()

    uploaded_file.seek(0)

    if name.endswith(".csv"):
        return pd.read_csv(
            uploaded_file
        )

    if source == "Sale Register":
        xls = pd.ExcelFile(
            uploaded_file
        )

        sheet = (
            "MSD"
            if "MSD" in xls.sheet_names
            else xls.sheet_names[-1]
        )

        return pd.read_excel(
            xls,
            sheet_name=sheet,
        )

    if source == "Mobikwik":
        xls = pd.ExcelFile(
            uploaded_file
        )

        sheet = (
            "Report"
            if "Report" in xls.sheet_names
            else xls.sheet_names[0]
        )

        return pd.read_excel(
            xls,
            sheet_name=sheet,
        )

    return pd.read_excel(
        uploaded_file
    )


@st.cache_data(show_spinner=False)
def load_tower(version=0):
    return build_control_tower(DATA)


if "data_version" not in st.session_state:
    st.session_state.data_version = 0


if "database_synced" not in st.session_state:
    try:
        with st.spinner(
            "Loading permanent data..."
        ):
            sync_database_to_local()

        st.session_state.database_synced = True

    except Exception as e:
        st.session_state.database_synced = False
        st.warning(
            f"Permanent database sync unavailable: {e}"
        )


st.title(
    "Website Order Control Tower"
)

st.caption(
    "Order → Fulfilment → Billing → Payment → "
    "Settlement → Refund/CN → Closure"
)


with st.sidebar:
    st.header(
        "Navigation"
    )

    page = st.radio(
        "",
        [
            "Dashboard",
            "Order Control Tower",
            "Exceptions",
            "Payment Reconciliation",
            "Upload Centre",
            "Source Health",
        ],
        label_visibility="collapsed",
    )

    st.divider()

    st.caption(
        "Glen Website Orders • Neon PostgreSQL"
    )


ct, matches, unmatched, raw = load_tower(
    st.session_state.data_version
)


def apply_global_date_filter(
    ct,
    matches,
):
    if (
        ct.empty
        or "Created at" not in ct.columns
    ):
        return (
            ct,
            matches,
            "All dates",
        )

    dates = pd.to_datetime(
        ct["Created at"],
        errors="coerce",
    )

    valid = dates.dropna()

    if valid.empty:
        return (
            ct,
            matches,
            "All dates",
        )

    min_d = valid.min().date()
    max_d = valid.max().date()

    with st.sidebar:
        st.divider()

        st.subheader(
            "Date Filter"
        )

        mode = st.selectbox(
            "Period",
            [
                "Date Range",
                "Weekly",
                "Monthly",
                "Quarterly",
                "Half Yearly",
                "Yearly",
            ],
            key="global_period_mode",
        )

        start = min_d
        end = max_d

        label = (
            f"{min_d:%d %b %Y} – "
            f"{max_d:%d %b %Y}"
        )

        if mode == "Date Range":
            picked = st.date_input(
                "Order Date Range",
                value=(
                    min_d,
                    max_d,
                ),
                min_value=min_d,
                max_value=max_d,
                key="global_date_range",
            )

            if (
                isinstance(
                    picked,
                    (tuple, list),
                )
                and len(picked) == 2
            ):
                start, end = picked

            elif picked:
                start = picked
                end = picked

            label = (
                f"{start:%d %b %Y} – "
                f"{end:%d %b %Y}"
            )

        else:
            tmp = pd.DataFrame(
                {"d": valid}
            )

            if mode == "Weekly":
                iso = (
                    tmp["d"]
                    .dt.isocalendar()
                )

                tmp["key"] = (
                    iso["year"].astype(str)
                    + "-W"
                    + iso["week"]
                    .astype(str)
                    .str.zfill(2)
                )

                tmp["label"] = (
                    tmp["d"]
                    .dt.to_period("W-MON")
                    .astype(str)
                )

            elif mode == "Monthly":
                tmp["key"] = (
                    tmp["d"]
                    .dt.to_period("M")
                    .astype(str)
                )

                tmp["label"] = (
                    tmp["d"]
                    .dt.strftime("%b %Y")
                )

            elif mode == "Quarterly":
                tmp["key"] = (
                    tmp["d"]
                    .dt.to_period("Q")
                    .astype(str)
                )

                tmp["label"] = (
                    "Q"
                    + tmp["d"]
                    .dt.quarter.astype(str)
                    + " "
                    + tmp["d"]
                    .dt.year.astype(str)
                )

            elif mode == "Half Yearly":
                half = (
                    (
                        tmp["d"].dt.month
                        - 1
                    )
                    // 6
                    + 1
                )

                tmp["key"] = (
                    tmp["d"]
                    .dt.year.astype(str)
                    + "-H"
                    + half.astype(str)
                )

                tmp["label"] = (
                    "H"
                    + half.astype(str)
                    + " "
                    + tmp["d"]
                    .dt.year.astype(str)
                )

            else:
                tmp["key"] = (
                    tmp["d"]
                    .dt.year.astype(str)
                )

                tmp["label"] = (
                    tmp["key"]
                )

            periods = (
                tmp[
                    [
                        "key",
                        "label",
                    ]
                ]
                .drop_duplicates()
                .sort_values(
                    "key",
                    ascending=False,
                )
            )

            options = (
                periods["key"]
                .tolist()
            )

            labels = dict(
                zip(
                    periods["key"],
                    periods["label"],
                )
            )

            chosen = st.selectbox(
                f"Select {mode}",
                options,
                index=0,
                format_func=lambda x: labels.get(
                    x,
                    x,
                ),
                key=f"global_{mode}",
            )

            dsel = tmp.loc[
                tmp["key"] == chosen,
                "d",
            ]

            start = (
                dsel.min().date()
            )

            end = (
                dsel.max().date()
            )

            label = labels.get(
                chosen,
                chosen,
            )

        st.caption(
            f"Applied: {label}"
        )

    mask = (
        (dates.dt.date >= start)
        & (dates.dt.date <= end)
    )

    filtered = (
        ct.loc[mask]
        .copy()
    )

    if (
        not matches.empty
        and "Order No"
        in matches.columns
    ):
        matches = matches[
            matches["Order No"].isin(
                set(
                    filtered[
                        "Order No"
                    ]
                )
            )
        ].copy()

    return (
        filtered,
        matches,
        label,
    )


# =========================================================
# DASHBOARD COMPARISON ENGINE
# =========================================================

@st.cache_data(show_spinner=False)
def load_dashboard_msd(version=0):
    """Read the MSD sheet without applying Shopify-only normalization."""
    path = source_path(DATA, "Sale Register")
    if not path.exists():
        return pd.DataFrame()

    xls = pd.ExcelFile(path)
    sheet = "MSD" if "MSD" in xls.sheet_names else xls.sheet_names[-1]
    df = pd.read_excel(xls, sheet_name=sheet)

    for col in ["Po Number", "Invoice No", "Document Type"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()

    if "Invoice Date" not in df.columns:
        df["Invoice Date"] = pd.NaT
    df["Invoice Date"] = pd.to_datetime(df["Invoice Date"], errors="coerce")

    if "Gross Amount" not in df.columns:
        df["Gross Amount"] = 0.0
    df["Gross Amount"] = pd.to_numeric(df["Gross Amount"], errors="coerce").fillna(0.0)

    df["MSD Order No"] = df["Po Number"]
    df["Document Type Clean"] = df["Document Type"].str.lower()
    return df


def _strict_shopify_match(value, shopify_orders):
    """Match MSD PO to Shopify only when the PO itself is the order number."""
    s = "" if pd.isna(value) else str(value).strip()
    if not re.fullmatch(r"#[0-9]+", s):
        return ""
    return s if s in shopify_orders else ""


def _join_unique(values):
    out = []
    for value in values:
        if pd.isna(value):
            continue
        s = str(value).strip()
        if s and s not in out:
            out.append(s)
    return ", ".join(out)


def _dashboard_date_window(dates, basis_key):
    dates = pd.to_datetime(dates, errors="coerce")
    valid = dates.dropna()
    if valid.empty:
        return None, None, "All dates"

    min_d = valid.min().date()
    max_d = valid.max().date()

    with st.sidebar:
        st.subheader("Date Filter")
        mode = st.selectbox(
            "Period",
            ["Date Range", "Weekly", "Monthly", "Quarterly", "Half Yearly", "Yearly"],
            key=f"dashboard_period_{basis_key}",
        )

        start, end = min_d, max_d
        label = f"{min_d:%d %b %Y} – {max_d:%d %b %Y}"

        if mode == "Date Range":
            picked = st.date_input(
                "Date Range",
                value=(min_d, max_d),
                min_value=min_d,
                max_value=max_d,
                key=f"dashboard_date_range_{basis_key}",
            )
            if isinstance(picked, (tuple, list)) and len(picked) == 2:
                start, end = picked
            elif picked:
                start = end = picked
            label = f"{start:%d %b %Y} – {end:%d %b %Y}"
        else:
            tmp = pd.DataFrame({"d": valid})
            if mode == "Weekly":
                iso = tmp["d"].dt.isocalendar()
                tmp["key"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
                tmp["label"] = "W" + iso["week"].astype(str).str.zfill(2) + " " + iso["year"].astype(str)
            elif mode == "Monthly":
                tmp["key"] = tmp["d"].dt.to_period("M").astype(str)
                tmp["label"] = tmp["d"].dt.strftime("%b %Y")
            elif mode == "Quarterly":
                tmp["key"] = tmp["d"].dt.to_period("Q").astype(str)
                tmp["label"] = "Q" + tmp["d"].dt.quarter.astype(str) + " " + tmp["d"].dt.year.astype(str)
            elif mode == "Half Yearly":
                half = ((tmp["d"].dt.month - 1) // 6 + 1)
                tmp["key"] = tmp["d"].dt.year.astype(str) + "-H" + half.astype(str)
                tmp["label"] = "H" + half.astype(str) + " " + tmp["d"].dt.year.astype(str)
            else:
                tmp["key"] = tmp["d"].dt.year.astype(str)
                tmp["label"] = tmp["key"]

            periods = tmp[["key", "label"]].drop_duplicates().sort_values("key", ascending=False)
            options = periods["key"].tolist()
            labels = dict(zip(periods["key"], periods["label"]))
            chosen = st.selectbox(
                f"Select {mode}",
                options,
                index=0,
                format_func=lambda x: labels.get(x, x),
                key=f"dashboard_select_{mode}_{basis_key}",
            )
            dsel = tmp.loc[tmp["key"] == chosen, "d"]
            start, end = dsel.min().date(), dsel.max().date()
            label = labels.get(chosen, chosen)

        st.caption(f"Applied: {label}")

    return start, end, label


def _aggregate_msd_rows(msd_rows, group_col):
    """One row per order/PO with invoice and CN totals kept separate."""
    if msd_rows.empty:
        return pd.DataFrame(columns=[group_col, "Invoice_No", "Invoice_Date", "Invoice_Value", "CN_No", "CN_Date", "CN_Value"])

    rows = []
    for key, grp in msd_rows.groupby(group_col, dropna=False):
        doc = grp["Document Type Clean"]
        inv = grp[doc.eq("invoice")]
        cn = grp[doc.str.contains("credit|return|cn", regex=True, na=False)]
        rows.append({
            group_col: key,
            "Invoice_No": _join_unique(inv["Invoice No"]),
            "Invoice_Date": inv["Invoice Date"].max() if not inv.empty else pd.NaT,
            "Invoice_Value": float(inv["Gross Amount"].sum()) if not inv.empty else 0.0,
            "CN_No": _join_unique(cn["Invoice No"]),
            "CN_Date": cn["Invoice Date"].max() if not cn.empty else pd.NaT,
            "CN_Value": float(cn["Gross Amount"].abs().sum()) if not cn.empty else 0.0,
        })
    return pd.DataFrame(rows)


def build_dashboard_context(ct_all, version=0):
    msd = load_dashboard_msd(version).copy()
    shopify_orders = set(ct_all["Order No"].dropna().astype(str)) if not ct_all.empty else set()
    if not msd.empty:
        msd["Shopify Order No"] = msd["MSD Order No"].map(lambda x: _strict_shopify_match(x, shopify_orders))

    with st.sidebar:
        st.divider()
        st.subheader("Dashboard Comparison")
        basis = st.selectbox(
            "Comparison against",
            ["Shopify Orders", "MSD (Sale Register)"],
            key="dashboard_comparison_basis",
        )

    if basis == "Shopify Orders":
        start, end, label = _dashboard_date_window(ct_all["Created at"], "shopify")
        dates = pd.to_datetime(ct_all["Created at"], errors="coerce")
        mask = (dates.dt.date >= start) & (dates.dt.date <= end)
        shop = ct_all.loc[mask].copy()

        selected_orders = set(shop["Order No"].astype(str))
        linked = msd[msd["Shopify Order No"].isin(selected_orders)].copy() if not msd.empty else pd.DataFrame()
        msd_agg = _aggregate_msd_rows(linked, "Shopify Order No")

        # Discard the control-tower invoice/CN values here and rebuild them directly
        # from MSD so Dashboard totals cannot be multiplied by merge artefacts.
        for col in ["Invoice_No", "Invoice_Date", "Invoice_Value", "CN_No", "CN_Date", "CN_Value"]:
            if col in shop.columns:
                shop = shop.drop(columns=[col])
        shop = shop.merge(msd_agg, left_on="Order No", right_on="Shopify Order No", how="left")
        if "Shopify Order No" in shop.columns:
            shop = shop.drop(columns=["Shopify Order No"])

        for col in ["Invoice_Value", "CN_Value"]:
            shop[col] = pd.to_numeric(shop.get(col, 0), errors="coerce").fillna(0.0)
        for col in ["Invoice_No", "CN_No"]:
            shop[col] = shop.get(col, "").fillna("")

        total = pd.to_numeric(shop.get("Total", 0), errors="coerce").fillna(0)
        shop["Billing Status"] = pd.Series("Unbilled", index=shop.index)
        shop.loc[shop["Invoice_Value"] > 0, "Billing Status"] = "Billed"
        partial = (shop["Invoice_Value"] > 0) & ((shop["Invoice_Value"] + 1) < total)
        shop.loc[partial, "Billing Status"] = "Partially Billed"

        comp = shop[[c for c in [
            "Order No", "Created at", "Billing Name", "Subtotal", "Total",
            "Invoice_No", "Invoice_Date", "Invoice_Value", "CN_No", "CN_Date", "CN_Value"
        ] if c in shop.columns]].copy()
        comp["Difference"] = comp["Invoice_Value"] - pd.to_numeric(comp["Subtotal"], errors="coerce").fillna(0)
        comp["Reconciliation Status"] = "Matched"
        comp.loc[comp["Invoice_Value"].eq(0), "Reconciliation Status"] = "No MSD Invoice"
        comp.loc[comp["Difference"] > 1, "Reconciliation Status"] = "MSD Invoice Higher"
        comp.loc[(comp["Invoice_Value"] > 0) & (comp["Difference"] < -1), "Reconciliation Status"] = "MSD Invoice Lower"

        return {
            "basis": basis,
            "date_label": label,
            "date_basis": "Shopify Created at",
            "status_scope": shop,
            "comparison": comp,
            "order_count": len(shop),
            "order_value": pd.to_numeric(shop.get("Subtotal", 0), errors="coerce").fillna(0).sum(),
            "invoice_value": shop["Invoice_Value"].sum(),
            "cn_value": shop["CN_Value"].sum(),
        }

    # MSD basis: date range is applied to MSD Invoice Date, not Shopify Created at.
    start, end, label = _dashboard_date_window(msd["Invoice Date"] if not msd.empty else pd.Series(dtype="datetime64[ns]"), "msd")
    dates = pd.to_datetime(msd["Invoice Date"], errors="coerce")
    mask = (dates.dt.date >= start) & (dates.dt.date <= end)
    msd_scope = msd.loc[mask].copy()
    msd_agg = _aggregate_msd_rows(msd_scope, "MSD Order No")

    order_to_shop = (
        msd_scope.groupby("MSD Order No")["Shopify Order No"]
        .apply(lambda s: next((v for v in s if str(v).strip()), ""))
        .rename("Shopify Order No")
        .reset_index()
        if not msd_scope.empty else pd.DataFrame(columns=["MSD Order No", "Shopify Order No"])
    )
    msd_agg = msd_agg.merge(order_to_shop, on="MSD Order No", how="left")

    shop_cols = [c for c in [
        "Order No", "Created at", "Billing Name", "Subtotal", "Total", "Order Status",
        "Fulfilment Status", "Settlement Status", "Final Closure", "Exception Reason"
    ] if c in ct_all.columns]
    shop_lookup = ct_all[shop_cols].drop_duplicates("Order No").copy()
    msd_agg = msd_agg.merge(shop_lookup, left_on="Shopify Order No", right_on="Order No", how="left")

    msd_agg["Shopify Match"] = msd_agg["Order No"].notna().map({True: "Matched", False: "MSD Only / Not in Shopify"})
    msd_agg["Shopify Subtotal"] = pd.to_numeric(msd_agg.get("Subtotal", 0), errors="coerce").fillna(0)
    msd_agg["Difference"] = msd_agg["Invoice_Value"] - msd_agg["Shopify Subtotal"]
    msd_agg["Reconciliation Status"] = msd_agg["Shopify Match"]
    matched = msd_agg["Shopify Match"].eq("Matched")
    msd_agg.loc[matched & (msd_agg["Difference"].abs() <= 1), "Reconciliation Status"] = "Matched"
    msd_agg.loc[matched & (msd_agg["Difference"] > 1), "Reconciliation Status"] = "MSD Invoice Higher"
    msd_agg.loc[matched & (msd_agg["Difference"] < -1), "Reconciliation Status"] = "MSD Invoice Lower"

    matched_shop = msd_agg[matched & msd_agg["Order No"].notna()].copy()
    # One Shopify order only once even if the MSD source somehow contains aliases.
    matched_shop = matched_shop.drop_duplicates("Order No")

    # In MSD mode the universe is the Sale Register itself, not only invoice orders.
    # Count each MSD PO once across Invoice + Credit Memo documents.
    all_msd_orders = int(msd_agg["MSD Order No"].nunique())
    invoice_orders = int(msd_agg.loc[msd_agg["Invoice_Value"].ne(0), "MSD Order No"].nunique())
    return_orders = int(msd_agg.loc[msd_agg["CN_Value"].ne(0), "MSD Order No"].nunique())
    cn_only_orders = int(msd_agg.loc[msd_agg["Invoice_Value"].eq(0) & msd_agg["CN_Value"].ne(0), "MSD Order No"].nunique())

    # Shopify subtotal is supplementary in MSD mode: sum it once for matched MSD POs.
    return_matched = msd_agg[matched & msd_agg["CN_Value"].ne(0)].drop_duplicates("Order No")
    return_order_value = return_matched["Shopify Subtotal"].sum() if not return_matched.empty else 0.0

    return {
        "basis": basis,
        "date_label": label,
        "date_basis": "MSD Invoice Date",
        "status_scope": matched_shop,
        "comparison": msd_agg,
        "order_count": all_msd_orders,
        "order_value": matched_shop["Shopify Subtotal"].sum() if not matched_shop.empty else 0.0,
        "invoice_value": msd_agg["Invoice_Value"].sum(),
        "cn_value": msd_agg["CN_Value"].sum(),
        "billed_count": invoice_orders,
        "billed_value": msd_agg["Invoice_Value"].sum(),
        "return_count": return_orders,
        "return_order_value": return_order_value,
        "cn_only_count": cn_only_orders,
    }


if page == "Dashboard":
    dashboard_ctx = build_dashboard_context(ct, st.session_state.data_version)
    ct = dashboard_ctx["status_scope"].copy()
    date_filter_label = dashboard_ctx["date_label"]
    if not matches.empty and "Order No" in matches.columns and "Order No" in ct.columns:
        matches = matches[matches["Order No"].isin(set(ct["Order No"].dropna().astype(str)))].copy()
else:
    dashboard_ctx = None
    ct, matches, date_filter_label = apply_global_date_filter(ct, matches)


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


def show_selected_date_kpis(df, selected_date_label, dashboard_ctx=None):
    """Dashboard KPI matrix using the selected comparison basis."""
    if dashboard_ctx is None:
        dashboard_ctx = {
            "basis": "Shopify Orders",
            "date_basis": "Shopify Created at",
            "order_count": len(df),
            "order_value": _kpi_sum(df, "Subtotal"),
            "invoice_value": _kpi_sum(df, "Invoice_Value"),
            "cn_value": _kpi_sum(df, "CN_Value"),
        }

    st.caption(
        f"Comparison: {dashboard_ctx['basis']}  •  "
        f"Date basis: {dashboard_ctx['date_basis']}  •  {selected_date_label}"
    )

    order_count = int(dashboard_ctx.get("order_count", len(df)))
    order_value = float(dashboard_ctx.get("order_value", 0) or 0)
    invoice_value = float(dashboard_ctx.get("invoice_value", 0) or 0)
    cn_value = float(dashboard_ctx.get("cn_value", 0) or 0)

    subtotal = pd.to_numeric(df.get("Subtotal", df.get("Shopify Subtotal", 0)), errors="coerce").fillna(0) if not df.empty else pd.Series(dtype=float)
    invoice = pd.to_numeric(df.get("Invoice_Value", 0), errors="coerce").fillna(0) if not df.empty else pd.Series(dtype=float)

    cancelled_mask = df.get("Order Status", pd.Series(index=df.index, dtype=object)).eq("Cancelled")
    fulfilled_mask = df.get("Fulfilment Status", pd.Series(index=df.index, dtype=object)).eq("Fulfilled")

    is_msd = dashboard_ctx.get("basis") == "MSD (Sale Register)"
    if is_msd:
        billed_mask = invoice.ne(0)
        not_billed_mask = invoice.eq(0)
    else:
        billed_mask = df.get("Billing Status", pd.Series(index=df.index, dtype=object)).eq("Billed")
        not_billed_mask = ~billed_mask

    action_mask = df.get("Final Closure", pd.Series(index=df.index, dtype=object)).eq("Action Required")

    if is_msd:
        # MSD mode: Sale Register is the master universe. Return/CN orders are part of
        # Order Count, and the return count is shown separately. Shopify status KPIs
        # below are supplementary and apply only where the MSD PO matched Shopify.
        rows = [
            ("Order Count", order_count, "Order Subtotal Value", order_value, "Invoice Value", invoice_value),
            ("Return/CN Count", int(dashboard_ctx.get("return_count", 0)), "Return/CN Order Value", float(dashboard_ctx.get("return_order_value", 0) or 0), "CN Value", cn_value),
            ("Shopify Fulfilled Count", int(fulfilled_mask.sum()), "Shopify Fulfilled Value", subtotal[fulfilled_mask].sum(), None, None),
            ("Billed Count", int(dashboard_ctx.get("billed_count", 0)), "Billed Value", float(dashboard_ctx.get("billed_value", invoice_value) or 0), None, None),
            ("CN-only MSD Count", int(dashboard_ctx.get("cn_only_count", 0)), "CN-only Shopify Value", subtotal[not_billed_mask].sum(), None, None),
            ("Action Required Count", int(action_mask.sum()), "Action Required Value", subtotal[action_mask].sum(), None, None),
        ]
    else:
        rows = [
            ("Order Count", order_count, "Order Subtotal Value", order_value, "Invoice Value", invoice_value),
            ("Cancelled Count", int(cancelled_mask.sum()), "Cancelled Value", subtotal[cancelled_mask].sum(), "CN Value", cn_value),
            ("Fulfilled Count", int(fulfilled_mask.sum()), "Fulfilled Value", subtotal[fulfilled_mask].sum(), None, None),
            ("Billed Count", int(billed_mask.sum()), "Billed Value", invoice[billed_mask].sum(), None, None),
            ("Order Not Billed Count", int(not_billed_mask.sum()), "Order Not Billed Value", subtotal[not_billed_mask].sum(), None, None),
            ("Action Required Count", int(action_mask.sum()), "Action Required Value", subtotal[action_mask].sum(), None, None),
        ]

    for count_label, count_value, value_label, value_value, finance_label, finance_value in rows:
        c1, c2, c3 = st.columns(3)
        c1.metric(count_label, f"{count_value:,}")
        c2.metric(value_label, _format_inr_kpi(value_value))
        if finance_label:
            c3.metric(finance_label, _format_inr_kpi(finance_value))

    st.divider()




if page == "Upload Centre":
    st.subheader(
        "Data Upload Centre"
    )

    st.write(
        "Uploaded data is stored permanently in Neon PostgreSQL. "
        "New rows are inserted, changed rows are updated, "
        "and unchanged rows are skipped."
    )

    cols = st.columns(2)

    for i, (
        source,
        fname,
    ) in enumerate(
        SOURCE_FILES.items()
    ):
        with cols[i % 2]:
            try:
                db_counts = (
                    get_database_counts()
                )

                source_row = db_counts[
                    db_counts["Source"]
                    == source
                ]

                db_rows = (
                    int(
                        source_row[
                            "Rows"
                        ].iloc[0]
                    )
                    if not source_row.empty
                    else 0
                )

            except Exception:
                db_rows = 0

            if db_rows > 0:
                status_text = (
                    f"✅ {db_rows:,} rows saved"
                )
            else:
                status_text = (
                    "⏳ Pending"
                )

            st.markdown(
                f"**{source}**  "
                f"{status_text}"
            )

            up = st.file_uploader(
                f"Upload {source}",
                type=[
                    "xlsx",
                    "xls",
                    "csv",
                ],
                key=f"up_{source}",
            )

            if up is not None:
                if st.button(
                    f"Save {source}",
                    key=f"save_{source}",
                    width="stretch",
                ):
                    try:
                        with st.spinner(
                            f"Saving {source}..."
                        ):
                            df_upload = (
                                read_uploaded_source(
                                    source,
                                    up,
                                )
                            )

                            if df_upload.empty:
                                st.warning(
                                    "Uploaded file contains no data."
                                )

                            else:
                                result = (
                                    upsert_dataframe(
                                        source,
                                        df_upload,
                                        file_name=up.name,
                                    )
                                )

                                if source == "Sale Register":
                                    persisted_df = read_source_from_database(
                                        source
                                    )

                                    if len(persisted_df) != len(df_upload):
                                        raise RuntimeError(
                                            "Sale Register row-count mismatch after database save: "
                                            f"uploaded={len(df_upload):,}, "
                                            f"database={len(persisted_df):,}. "
                                            "Local cache was not replaced."
                                        )

                                    save_local_source(
                                        source,
                                        persisted_df,
                                    )
                                else:
                                    save_local_source(
                                        source,
                                        df_upload,
                                    )

                                st.session_state.data_version += 1

                                st.cache_data.clear()

                        st.success(
                            f"{source} saved successfully."
                        )

                        m1, m2, m3, m4, m5 = (
                            st.columns(5)
                        )

                        m1.metric(
                            "Rows in File",
                            f"{result['total']:,}",
                        )

                        m2.metric(
                            "New",
                            f"{result['new']:,}",
                        )

                        m3.metric(
                            "Updated",
                            f"{result['updated']:,}",
                        )

                        m4.metric(
                            "Skipped",
                            f"{result['skipped']:,}",
                        )

                        m5.metric(
                            "Failed",
                            f"{result['failed']:,}",
                        )

                    except Exception as e:
                        st.error(
                            f"Upload failed: {e}"
                        )

    st.divider()

    st.markdown(
        "#### Permanent Database Status"
    )

    try:
        db_counts = (
            get_database_counts()
        )

        st.dataframe(
            db_counts,
            width="stretch",
            hide_index=True,
        )

    except Exception as e:
        st.warning(
            f"Database status unavailable: {e}"
        )

    st.markdown(
        "#### Upload History"
    )

    try:
        history = (
            get_upload_history(50)
        )

        if history.empty:
            st.info(
                "No database uploads recorded yet."
            )

        else:
            st.dataframe(
                history,
                width="stretch",
                hide_index=True,
            )

    except Exception as e:
        st.warning(
            f"Upload history unavailable: {e}"
        )


elif ct.empty:
    st.error(
        "Shopify Orders is required to build the control tower. "
        "Please upload it in Upload Centre."
    )


elif page == "Dashboard":
    show_selected_date_kpis(ct, date_filter_label, dashboard_ctx)

    st.markdown("#### Shopify ↔ MSD Reconciliation")
    comp = dashboard_ctx["comparison"].copy()
    diff_only = st.checkbox("Show differences only", value=True, key="dashboard_differences_only")
    if diff_only and "Reconciliation Status" in comp.columns:
        comp = comp[comp["Reconciliation Status"].ne("Matched")].copy()

    preferred = [
        "MSD Order No", "Order No", "Shopify Order No", "Created at", "Billing Name",
        "Subtotal", "Shopify Subtotal", "Invoice_No", "Invoice_Date", "Invoice_Value",
        "CN_No", "CN_Date", "CN_Value", "Difference", "Shopify Match", "Reconciliation Status"
    ]
    preferred = [c for c in preferred if c in comp.columns]
    st.dataframe(comp[preferred], width="stretch", hide_index=True)
    st.caption(
        "Shopify mode: the date range selects Shopify orders by Created at, then MSD invoice/CN values are taken only for those order numbers. "
        "MSD mode: the date range selects MSD rows by Invoice Date, and Shopify details are attached only where the MSD Po Number exactly matches a Shopify order number."
    )

    c1, c2 = (
        st.columns(2)
    )

    with c1:
        st.markdown(
            "#### Lifecycle Status"
        )

        life = pd.DataFrame(
            {
                "Status": [
                    "Fulfilled",
                    "Unfulfilled",
                    "Billed",
                    "Unbilled",
                    "Settled",
                    "Unsettled",
                ],
                "Orders": [
                    (
                        ct[
                            "Fulfilment Status"
                        ]
                        == "Fulfilled"
                    ).sum(),
                    (
                        ct[
                            "Fulfilment Status"
                        ]
                        == "Unfulfilled"
                    ).sum(),
                    (
                        ct[
                            "Billing Status"
                        ]
                        == "Billed"
                    ).sum(),
                    (
                        ct[
                            "Billing Status"
                        ]
                        == "Unbilled"
                    ).sum(),
                    (
                        ct[
                            "Settlement Status"
                        ]
                        == "Settled"
                    ).sum(),
                    (ct["Settlement Status"] == "Unsettled").sum() if "Settlement Status" in ct.columns else 0,
                ],
            }
        ).set_index(
            "Status"
        )

        st.bar_chart(
            life
        )

    with c2:
        st.markdown(
            "#### Final Closure"
        )

        st.bar_chart(
            ct[
                "Final Closure"
            ].value_counts()
        )

    st.markdown(
        "#### Recent orders requiring action"
    )

    show = ct[
        ct["Final Closure"]
        == "Action Required"
    ].head(50)

    columns_to_show = [
        "Order No",
        "Created at",
        "Total",
        "Order Status",
        "Fulfilment Status",
        "Billing Status",
        "Payment Status",
        "Settlement Status",
        "CN Status",
        "Exception Reason",
    ]

    columns_to_show = [
        col
        for col
        in columns_to_show
        if col in show.columns
    ]

    st.dataframe(
        show[
            columns_to_show
        ],
        width="stretch",
        hide_index=True,
    )


elif page == "Order Control Tower":
    st.subheader(
        "Order-Level Control Tower"
    )

    st.caption(
        f"Order date: {date_filter_label}"
    )

    f1, f2, f3, f4 = (
        st.columns(4)
    )

    q = f1.text_input(
        "Search order / invoice / CN / customer / SKU"
    )

    order_status = (
        f2.multiselect(
            "Order Status",
            sorted(
                ct[
                    "Order Status"
                ]
                .dropna()
                .unique()
            ),
        )
    )

    billing = (
        f3.multiselect(
            "Billing Status",
            sorted(
                ct[
                    "Billing Status"
                ]
                .dropna()
                .unique()
            ),
        )
    )

    settlement = (
        f4.multiselect(
            "Settlement Status",
            sorted(
                ct[
                    "Settlement Status"
                ]
                .dropna()
                .unique()
            ),
        )
    )

    view = ct.copy()

    if q:
        mask = (
            view.astype(str)
            .apply(
                lambda s:
                s.str.contains(
                    q,
                    case=False,
                    na=False,
                )
            )
            .any(axis=1)
        )

        view = view[
            mask
        ]

    if order_status:
        view = view[
            view[
                "Order Status"
            ].isin(
                order_status
            )
        ]

    if billing:
        view = view[
            view[
                "Billing Status"
            ].isin(
                billing
            )
        ]

    if settlement:
        view = view[
            view[
                "Settlement Status"
            ].isin(
                settlement
            )
        ]

    st.caption(
        f"{len(view):,} orders shown"
    )

    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        height=600,
    )

    bio = io.BytesIO()

    with pd.ExcelWriter(
        bio,
        engine="xlsxwriter",
    ) as writer:
        view.to_excel(
            writer,
            index=False,
            sheet_name="Order Control Tower",
        )

    st.download_button(
        "Download filtered control tower",
        bio.getvalue(),
        "order_control_tower.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.divider()

    st.markdown(
        "#### Order drill-down"
    )

    order_options = (
        view["Order No"]
        .dropna()
        .astype(str)
        .tolist()[:5000]
        if len(view)
        else []
    )

    ono = st.selectbox(
        "Select Order No",
        order_options,
    )

    if ono:
        selected = ct[
            ct["Order No"]
            .astype(str)
            == str(ono)
        ]

        if not selected.empty:
            r = (
                selected.iloc[0]
            )

            k1, k2, k3, k4 = (
                st.columns(4)
            )

            k1.metric(
                "Order Value",
                f"₹{r['Total']:,.0f}",
            )

            k2.metric(
                "Billing",
                r["Billing Status"],
            )

            k3.metric(
                "Payment",
                r["Payment Status"],
            )

            k4.metric(
                "Closure",
                r["Final Closure"],
            )

            st.dataframe(
                pd.DataFrame(
                    {
                        "Field": r.index,
                        "Value": [
                            str(x)
                            for x
                            in r.values
                        ],
                    }
                ),
                width="stretch",
                hide_index=True,
            )

            if not matches.empty:
                st.markdown(
                    "##### Matched payment transactions"
                )

                st.dataframe(
                    matches[
                        matches[
                            "Order No"
                        ]
                        == ono
                    ],
                    width="stretch",
                    hide_index=True,
                )


elif page == "Exceptions":
    st.subheader(
        "Exception Control Tower"
    )

    st.caption(
        f"Order date: {date_filter_label}"
    )

    ex = ct[
        ct[
            "Exception Reason"
        ].ne("")
    ].copy()

    reasons = sorted(
        set(
            x.strip()
            for s in ex[
                "Exception Reason"
            ]
            for x in str(s).split(";")
            if x.strip()
        )
    )

    sel = st.multiselect(
        "Exception type",
        reasons,
    )

    if sel:
        ex = ex[
            ex[
                "Exception Reason"
            ].apply(
                lambda x:
                any(
                    s in str(x)
                    for s in sel
                )
            )
        ]

    st.metric(
        "Orders requiring action",
        f"{len(ex):,}",
    )

    exception_columns = [
        "Order No",
        "Created at",
        "Billing Name",
        "Total",
        "Order Status",
        "Fulfilment Status",
        "Billing Status",
        "Payment Status",
        "Settlement Status",
        "CN Status",
        "Exception Reason",
    ]

    exception_columns = [
        c
        for c
        in exception_columns
        if c in ex.columns
    ]

    st.dataframe(
        ex[
            exception_columns
        ],
        width="stretch",
        hide_index=True,
        height=620,
    )


elif page == "Payment Reconciliation":
    st.subheader(
        "Payment & Settlement Reconciliation"
    )

    st.caption(
        f"Order date: {date_filter_label}"
    )

    if matches.empty:
        st.warning(
            "No exact gateway matches found."
        )

    else:
        p1, p2, p3 = (
            st.columns(3)
        )

        p1.metric(
            "Matched transactions",
            f"{len(matches):,}",
        )

        p2.metric(
            "Matched collection",
            f"₹{matches['Txn_Amount'].sum():,.0f}",
        )

        p3.metric(
            "Net settlement",
            f"₹{matches['Net_Settlement'].sum():,.0f}",
        )

        g = (
            matches.groupby(
                "Gateway",
                as_index=False,
            )
            .agg(
                Transactions=(
                    "Order No",
                    "size",
                ),
                Collection=(
                    "Txn_Amount",
                    "sum",
                ),
                Settlement=(
                    "Net_Settlement",
                    "sum",
                ),
            )
        )

        st.dataframe(
            g,
            width="stretch",
            hide_index=True,
        )

        if (
            "Settlement_Date"
            in matches.columns
        ):
            payment_view = (
                matches.sort_values(
                    "Settlement_Date",
                    ascending=False,
                )
            )

        else:
            payment_view = (
                matches
            )

        st.dataframe(
            payment_view,
            width="stretch",
            hide_index=True,
            height=480,
        )

    st.markdown(
        "#### Unmatched gateway rows"
    )

    st.caption(
        "These are deliberately not force-matched. "
        "They need a trustworthy Shopify reference "
        "or later manual mapping logic."
    )

    for source, df in unmatched:
        with st.expander(
            f"{source}: "
            f"{len(df):,} unmatched rows"
        ):
            st.dataframe(
                df.head(300),
                width="stretch",
                hide_index=True,
            )


elif page == "Source Health":
    st.subheader(
        "Source Health"
    )

    local_status = (
        available_sources(DATA)
    )

    try:
        db_counts = (
            get_database_counts()
        )

        count_map = dict(
            zip(
                db_counts["Source"],
                db_counts["Rows"],
            )
        )

    except Exception:
        count_map = {}

    rows = []

    for source, ok in (
        local_status.items()
    ):
        path = (
            source_path(
                DATA,
                source,
            )
        )

        db_rows = int(
            count_map.get(
                source,
                0,
            )
        )

        rows.append(
            {
                "Source": source,
                "Permanent DB Rows": db_rows,
                "DB Status": (
                    "Saved"
                    if db_rows > 0
                    else "Pending"
                ),
                "Local Cache": (
                    "Loaded"
                    if ok
                    else "Pending"
                ),
                "File": path.name,
                "Size KB": (
                    round(
                        path.stat().st_size
                        / 1024,
                        1,
                    )
                    if ok
                    else None
                ),
            }
        )

    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
    )

    st.markdown(
        "#### Current reconciliation coverage"
    )

    st.write(
        f"**Shopify orders:** "
        f"{len(ct):,}"
    )

    st.write(
        f"**Exact matched gateway transactions:** "
        f"{len(matches):,}"
    )

    if (
        "Billing Status"
        in ct.columns
    ):
        st.write(
            f"**Billed orders:** "
            f"{(ct['Billing Status'] == 'Billed').sum():,}"
        )

    if (
        "Final Closure"
        in ct.columns
    ):
        st.write(
            f"**Orders requiring action:** "
            f"{(ct['Final Closure'] == 'Action Required').sum():,}"
        )

    st.markdown(
        "#### Recent Upload History"
    )

    try:
        history = (
            get_upload_history(25)
        )

        if history.empty:
            st.info(
                "No permanent uploads recorded yet."
            )

        else:
            st.dataframe(
                history,
                width="stretch",
                hide_index=True,
            )

    except Exception as e:
        st.warning(
            f"Upload history unavailable: {e}"
        )