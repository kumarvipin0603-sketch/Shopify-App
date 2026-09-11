from pathlib import Path
import io

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
        "Navigation",
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


ct, matches, date_filter_label = (
    apply_global_date_filter(
        ct,
        matches,
    )
)


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
    st.caption(
        f"Order date: {date_filter_label}"
    )

    total = len(ct)

    value = (
        ct["Total"].sum()
    )

    cancelled = (
        ct["Order Status"]
        == "Cancelled"
    ).sum()

    fulfilled = (
        ct["Fulfilment Status"]
        == "Fulfilled"
    ).sum()

    billed = (
        ct["Billing Status"]
        == "Billed"
    ).sum()

    unsettled = (
        ct["Settlement Status"]
        == "Unsettled"
    ).sum()

    action = (
        ct["Final Closure"]
        == "Action Required"
    ).sum()

    a, b, c, d, e, f = (
        st.columns(6)
    )

    a.metric(
        "Orders",
        f"{total:,}",
    )

    b.metric(
        "Order Value",
        f"₹{value / 1e7:.2f} Cr",
    )

    c.metric(
        "Cancelled",
        f"{cancelled:,}",
    )

    d.metric(
        "Fulfilled",
        f"{fulfilled:,}",
    )

    e.metric(
        "Billed",
        f"{billed:,}",
    )

    f.metric(
        "Action Required",
        f"{action:,}",
    )

    st.divider()

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
                    unsettled,
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