import hashlib
import json
import numbers
import re
from datetime import datetime

import pandas as pd
import psycopg2
import streamlit as st
from psycopg2.extras import Json, execute_values


SOURCE_TABLES = {
    "Shopify Orders": "shopify_orders_raw",
    "Sale Register": "sale_register_raw",
    "Website Team Update": "website_team_update_raw",
    "PayU Settlement - Glen": "payu_glen_raw",
    "PayU Settlement - Alda": "payu_alda_raw",
    "Razorpay": "razorpay_raw",
    "Snapmint": "snapmint_raw",
    "Mobikwik": "mobikwik_raw",
    "Paytm Gateway": "paytm_gateway_raw",
    "Paytm Wallet": "paytm_wallet_raw",
    "Paytm QR": "paytm_qr_raw",
    "Delhivery": "delhivery_raw",
    "Bluedart": "bluedart_raw",
    "GVV": "gvv_raw",
}


def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])


def clean_value(value):
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, bool):
        return value

    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")

    if isinstance(value, datetime):
        return value.isoformat(sep=" ")

    if isinstance(value, numbers.Integral):
        return str(int(value))

    if isinstance(value, numbers.Real):
        value = float(value)

        if value.is_integer():
            return str(int(value))

        return format(value, ".15g")

    return str(value).strip()


def normalize_key(value):
    if value is None:
        return ""

    value = str(value).strip().lower()
    value = re.sub(r"\s+", " ", value)

    return value


def row_hash(row_dict):
    payload = json.dumps(
        row_dict,
        sort_keys=True,
        default=str,
        ensure_ascii=False,
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def first_value(row, candidates):
    for col in candidates:
        if col in row:
            value = clean_value(row[col])

            if value not in (None, ""):
                return value

    return ""


def make_business_key(source, row):
    if source == "Shopify Orders":
        order_id = first_value(
            row,
            ["Id", "Order ID"]
        )

        order_no = first_value(
            row,
            ["Order No", "Name"]
        )

        sku = first_value(
            row,
            ["Lineitem sku", "SKU"]
        )

        product = first_value(
            row,
            ["Lineitem name", "Product"]
        )

        qty = first_value(
            row,
            ["Qty", "Lineitem quantity"]
        )

        price = first_value(
            row,
            ["Lineitem price", "Price"]
        )

        key = "|".join(
            [
                normalize_key(order_id),
                normalize_key(order_no),
                normalize_key(sku),
                normalize_key(product),
                normalize_key(qty),
                normalize_key(price),
            ]
        )

        if key.replace("|", ""):
            return key

    elif source == "Sale Register":
        invoice_no = first_value(
            row,
            [
                "Invoice No",
                "Invoice Number",
                "Document No",
            ],
        )

        po_no = first_value(
            row,
            [
                "Po Number",
                "PO Number",
                "Order No",
            ],
        )

        item = first_value(
            row,
            [
                "Item Code",
                "Item",
                "Material Code",
                "SKU",
            ],
        )

        document_type = first_value(
            row,
            ["Document Type"]
        )

        key = "|".join(
            [
                normalize_key(invoice_no),
                normalize_key(po_no),
                normalize_key(item),
                normalize_key(document_type),
            ]
        )

        if key.replace("|", ""):
            return key

    elif source in [
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

    elif source == "Razorpay":
        key = first_value(
            row,
            [
                "entity_id",
                "payment_id",
                "order_id",
            ],
        )

        if key:
            return normalize_key(key)

    elif source == "Snapmint":
        loan_id = first_value(
            row,
            ["LoanApp Id"]
        )

        payment_id = first_value(
            row,
            ["Shopify Payment ID"]
        )

        order_no = first_value(
            row,
            [
                "Order No.",
                "Shopify Order No.",
            ],
        )

        key = "|".join(
            [
                normalize_key(loan_id),
                normalize_key(payment_id),
                normalize_key(order_no),
            ]
        )

        if key.replace("|", ""):
            return key

    elif source == "Mobikwik":
        txn_id = first_value(
            row,
            ["Txn Id"]
        )

        order_id = first_value(
            row,
            ["Order Id"]
        )

        key = "|".join(
            [
                normalize_key(txn_id),
                normalize_key(order_id),
            ]
        )

        if key.replace("|", ""):
            return key

    elif source in [
        "Paytm Gateway",
        "Paytm Wallet",
        "Paytm QR",
    ]:
        key = first_value(
            row,
            [
                "transaction_id",
                "Transaction ID",
                "txn_id",
                "Txn ID",
            ],
        )

        if key:
            return normalize_key(key)

        key = first_value(
            row,
            ["order_id", "Order ID"]
        )

        if key:
            return normalize_key(key)

    elif source in [
        "Delhivery",
        "Bluedart",
    ]:
        awb = first_value(
            row,
            [
                "AWB",
                "AWB No",
                "AWB Number",
                "Waybill",
                "waybill",
            ],
        )

        order_no = first_value(
            row,
            [
                "Order No",
                "Order ID",
                "Order Number",
                "Reference No",
            ],
        )

        key = "|".join(
            [
                normalize_key(awb),
                normalize_key(order_no),
            ]
        )

        if key.replace("|", ""):
            return key

    elif source == "GVV":
        key = first_value(
            row,
            [
                "Transaction ID",
                "Txn ID",
                "Order No",
                "Reference No",
            ],
        )

        if key:
            return normalize_key(key)

    elif source == "Website Team Update":
        order_no = first_value(
            row,
            [
                "Order No",
                "Order ID",
                "Shopify Order No",
            ],
        )

        if order_no:
            return normalize_key(order_no)

    clean_row = {
        str(k): clean_value(v)
        for k, v in row.items()
    }

    return "hash:" + row_hash(clean_row)

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



def prepare_dataframe(df):
    df = df.copy()

    seen = {}
    new_columns = []

    for col in df.columns:
        col = str(col).strip()

        if col in seen:
            seen[col] += 1
            col = f"{col}_{seen[col]}"
        else:
            seen[col] = 0

        new_columns.append(col)

    df.columns = new_columns

    return df


def create_database_tables():
    conn = get_connection()

    try:
        cur = conn.cursor()

        for table in SOURCE_TABLES.values():
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id BIGSERIAL PRIMARY KEY,
                    business_key TEXT NOT NULL UNIQUE,
                    row_hash TEXT NOT NULL,
                    data JSONB NOT NULL,
                    source_file TEXT,
                    first_uploaded_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS
                idx_{table}_updated_at
                ON {table}(updated_at);
                """
            )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_history (
                id BIGSERIAL PRIMARY KEY,
                source_name TEXT NOT NULL,
                file_name TEXT,
                total_rows INTEGER DEFAULT 0,
                new_rows INTEGER DEFAULT 0,
                updated_rows INTEGER DEFAULT 0,
                skipped_rows INTEGER DEFAULT 0,
                failed_rows INTEGER DEFAULT 0,
                uploaded_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def upsert_dataframe(source, df, file_name=""):
    if source not in SOURCE_TABLES:
        raise ValueError(
            f"Unknown source: {source}"
        )

    create_database_tables()

    table = SOURCE_TABLES[source]
    df = prepare_dataframe(df)

    total_rows = len(df)

    prepared_rows = {}
    duplicate_skipped = 0
    duplicate_failed = 0

    for _, row in df.iterrows():
        row_dict = {
            str(col): clean_value(value)
            for col, value in row.items()
        }

        business_key = make_business_key(
            source,
            row_dict,
        )

        current_hash = row_hash(row_dict)

        if business_key in prepared_rows:
            previous_hash = prepared_rows[
                business_key
            ]["row_hash"]

            if previous_hash == current_hash:
                duplicate_skipped += 1
                continue

            duplicate_failed += 1

        prepared_rows[business_key] = {
            "business_key": business_key,
            "row_hash": current_hash,
            "data": row_dict,
        }

    conn = get_connection()

    try:
        cur = conn.cursor()

        cur.execute(
            f"""
            SELECT
                business_key,
                row_hash
            FROM {table}
            """
        )

        existing = {
            business_key: existing_hash
            for business_key, existing_hash
            in cur.fetchall()
        }

        new_rows = 0
        updated_rows = 0
        unchanged_rows = 0

        records_to_write = []

        for business_key, record in prepared_rows.items():
            current_hash = record["row_hash"]
            old_hash = existing.get(business_key)

            if old_hash is None:
                new_rows += 1

            elif old_hash == current_hash:
                unchanged_rows += 1
                continue

            else:
                updated_rows += 1

            records_to_write.append(
                (
                    business_key,
                    current_hash,
                    Json(record["data"]),
                    file_name,
                )
            )

        if records_to_write:
            execute_values(
                cur,
                f"""
                INSERT INTO {table}
                (
                    business_key,
                    row_hash,
                    data,
                    source_file
                )
                VALUES %s

                ON CONFLICT (business_key)
                DO UPDATE SET
                    row_hash = EXCLUDED.row_hash,
                    data = EXCLUDED.data,
                    source_file = EXCLUDED.source_file,
                    updated_at = NOW()
                """,
                records_to_write,
                page_size=500,
            )

        skipped_rows = (
            unchanged_rows
            + duplicate_skipped
        )

        failed_rows = duplicate_failed

        cur.execute(
            """
            INSERT INTO upload_history
            (
                source_name,
                file_name,
                total_rows,
                new_rows,
                updated_rows,
                skipped_rows,
                failed_rows
            )
            VALUES
            (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                source,
                file_name,
                total_rows,
                new_rows,
                updated_rows,
                skipped_rows,
                failed_rows,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return {
        "total": total_rows,
        "new": new_rows,
        "updated": updated_rows,
        "skipped": skipped_rows,
        "failed": failed_rows,
    }


def read_source_from_database(source):
    if source not in SOURCE_TABLES:
        raise ValueError(
            f"Unknown source: {source}"
        )

    create_database_tables()

    table = SOURCE_TABLES[source]

    conn = get_connection()

    try:
        cur = conn.cursor()

        cur.execute(
            f"""
            SELECT data
            FROM {table}
            ORDER BY id
            """
        )

        records = [
            row[0]
            for row in cur.fetchall()
        ]

    finally:
        conn.close()

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records)


def get_database_counts():
    create_database_tables()

    conn = get_connection()

    rows = []

    try:
        cur = conn.cursor()

        for source, table in SOURCE_TABLES.items():
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM {table}
                """
            )

            count = cur.fetchone()[0]

            rows.append(
                {
                    "Source": source,
                    "Rows": count,
                }
            )

    finally:
        conn.close()

    return pd.DataFrame(rows)


def get_upload_history(limit=100):
    create_database_tables()

    conn = get_connection()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                source_name,
                file_name,
                total_rows,
                new_rows,
                updated_rows,
                skipped_rows,
                failed_rows,
                uploaded_at
            FROM upload_history
            ORDER BY uploaded_at DESC
            LIMIT %s
            """,
            (limit,),
        )

        rows = cur.fetchall()

    finally:
        conn.close()

    columns = [
        "Source",
        "File",
        "Rows in File",
        "New",
        "Updated",
        "Skipped",
        "Failed",
        "Uploaded At",
    ]

    return pd.DataFrame(
        rows,
        columns=columns,
    )