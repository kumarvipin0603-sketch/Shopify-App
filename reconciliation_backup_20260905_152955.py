from __future__ import annotations
import io, os, re
from pathlib import Path
import pandas as pd
import numpy as np

SOURCE_FILES = {
    "Shopify Orders": "shopify_orders.xlsx",
    "Sale Register": "sale_register.xlsx",
    "Website Team Update": "website_team_update.xlsx",
    "PayU Settlement - Glen": "payu_glen.xlsx",
    "PayU Settlement - Alda": "payu_alda.xlsx",
    "Razorpay": "razorpay.xlsx",
    "Snapmint": "snapmint.xlsx",
    "Mobikwik": "mobikwik.xlsx",
    "Paytm Gateway": "paytm_gateway.xlsx",
    "Paytm Wallet": "paytm_wallet.xlsx",
    "Paytm QR": "paytm_qr.xlsx",
    "Delhivery": "delhivery.xlsx",
    "Bluedart": "bluedart.xlsx",
    "GVV": "gvv.xlsx",
}


def clean_str(v):
    if pd.isna(v): return ""
    s = str(v).strip()
    if s.lower() in {"nan", "none", "nat"}: return ""
    return s


def norm_order(v):
    s = clean_str(v)
    if not s: return ""
    m = re.search(r"#?([0-9]{4,})", s)
    return f"#{m.group(1)}" if m else s


def norm_id(v):
    return clean_str(v).replace("'", "")


def num(s):
    return pd.to_numeric(s, errors="coerce").fillna(0)


def dt(s):
    return pd.to_datetime(s, errors="coerce", dayfirst=False, utc=True).dt.tz_convert(None)


def read_excel(path_or_file, sheet_name=0, **kwargs):
    return pd.read_excel(path_or_file, sheet_name=sheet_name, **kwargs)


def source_path(data_dir: str | Path, source: str):
    return Path(data_dir) / SOURCE_FILES[source]


def available_sources(data_dir):
    p = Path(data_dir)
    return {k: (p / v).exists() for k, v in SOURCE_FILES.items()}


def load_shopify(data_dir):
    path = source_path(data_dir, "Shopify Orders")
    if not path.exists():
        return pd.DataFrame()
    df = read_excel(path)
    if "Order No" not in df.columns and "Name" in df.columns:
        df = df.rename(columns={"Name": "Order No", "Lineitem quantity": "Qty"})
    df["Order No"] = df["Order No"].map(norm_order)
    for c in ["Total","Refunded Amount","Outstanding Balance","Qty"]:
        if c in df: df[c] = num(df[c])
    for c in ["Created at","Paid at","Fulfilled at","Cancelled at"]:
        if c in df: df[c] = pd.to_datetime(df[c], errors="coerce", utc=True).dt.tz_convert(None)
    return df


def aggregate_shopify(df):
    if df.empty: return pd.DataFrame()
    def first_nonblank(s):
        for v in s:
            if clean_str(v): return v
        return np.nan
    grp = df.groupby("Order No", dropna=False)
    out = grp.agg({
        "Created at":"min", "Email":first_nonblank, "Financial Status":first_nonblank,
        "Paid at":"min", "Fulfillment Status":first_nonblank, "Fulfilled at":"max",
        "Total":"max", "Refunded Amount":"max", "Outstanding Balance":"max",
        "Cancelled at":"max", "Payment Method":first_nonblank, "Payment Reference":first_nonblank,
        "Payment ID":first_nonblank, "Billing Name":first_nonblank, "Billing Phone":first_nonblank,
        "Shipping Name":first_nonblank, "Shipping Phone":first_nonblank,
        "Shipping City":first_nonblank, "Shipping Province Name":first_nonblank,
        "Risk Level":first_nonblank,
    }).reset_index()
    sku_col = "Lineitem sku" if "Lineitem sku" in df.columns else None
    name_col = "Lineitem name" if "Lineitem name" in df.columns else None
    qty_col = "Qty" if "Qty" in df.columns else None
    if sku_col:
        skus = grp[sku_col].apply(lambda x: ", ".join(dict.fromkeys([clean_str(v) for v in x if clean_str(v)]))).rename("SKUs")
        out = out.merge(skus, on="Order No", how="left")
    if name_col:
        names = grp[name_col].apply(lambda x: " | ".join(dict.fromkeys([clean_str(v) for v in x if clean_str(v)]))).rename("Products")
        out = out.merge(names, on="Order No", how="left")
    if qty_col:
        q = grp[qty_col].sum().rename("Order Qty")
        out = out.merge(q, on="Order No", how="left")
    return out


def load_sales(data_dir):
    path = source_path(data_dir, "Sale Register")
    if not path.exists(): return pd.DataFrame()
    xl = pd.ExcelFile(path)
    sheet = "MSD" if "MSD" in xl.sheet_names else xl.sheet_names[-1]
    df = read_excel(path, sheet_name=sheet)
    if "Po Number" not in df.columns: return pd.DataFrame()
    df["Order No"] = df["Po Number"].map(norm_order)
    for c in ["Gross Amount","Quantity"]:
        if c in df: df[c] = num(df[c])
    if "Invoice Date" in df: df["Invoice Date"] = pd.to_datetime(df["Invoice Date"], errors="coerce")
    return df


def aggregate_sales(df):
    if df.empty: return pd.DataFrame(columns=["Order No"])
    inv = df[df["Document Type"].astype(str).str.lower().eq("invoice")] if "Document Type" in df else df.copy()
    credit_mask = df["Document Type"].astype(str).str.lower().str.contains("credit|return|cn", regex=True) if "Document Type" in df else pd.Series(False,index=df.index)
    credits = df[credit_mask].copy()
    g = inv.groupby("Order No")
    out = g.agg(
        Invoice_Value=("Gross Amount","sum"), Invoice_Qty=("Quantity","sum"),
        Invoice_Date=("Invoice Date","max") if "Invoice Date" in inv else ("Order No","size")
    ).reset_index()
    if "Invoice No" in inv:
        invnos = g["Invoice No"].apply(lambda x: ", ".join(dict.fromkeys([clean_str(v) for v in x if clean_str(v)]))).rename("Invoice_No")
        out = out.merge(invnos, on="Order No", how="left")
    if not credits.empty:
        cg=credits.groupby("Order No")["Gross Amount"].sum().abs().rename("CN_Value")
        out=out.merge(cg,on="Order No",how="left")
    out["CN_Value"] = out.get("CN_Value",0)
    return out


def _match_by_payment(master, tx, id_col, source, amount_col=None, net_col=None, date_col=None, utr_col=None, action_col=None):
    if tx.empty or id_col not in tx.columns: return pd.DataFrame()
    map_df = master[["Order No","Payment ID","Payment Reference"]].copy()
    pairs=[]
    for key in ["Payment ID","Payment Reference"]:
        p=map_df[["Order No",key]].copy(); p["match_id"]=p[key].map(norm_id); p=p[p["match_id"]!=""]
        pairs.append(p[["Order No","match_id"]])
    lk=pd.concat(pairs).drop_duplicates("match_id") if pairs else pd.DataFrame(columns=["Order No","match_id"])
    t=tx.copy(); t["match_id"]=t[id_col].map(norm_id)
    m=t.merge(lk,on="match_id",how="inner")
    if m.empty:return m
    m["Gateway"] = source
    m["Txn_Amount"] = num(m[amount_col]) if amount_col and amount_col in m else 0
    m["Net_Settlement"] = num(m[net_col]) if net_col and net_col in m else m["Txn_Amount"]
    m["Settlement_Date"] = pd.to_datetime(m[date_col],errors="coerce") if date_col and date_col in m else pd.NaT
    m["UTR"] = m[utr_col].map(clean_str) if utr_col and utr_col in m else ""
    m["Action"] = m[action_col].map(clean_str) if action_col and action_col in m else "capture"
    m["Match_Method"] = f"Exact {id_col} → Shopify Payment ID"
    return m[["Order No","Gateway","Txn_Amount","Net_Settlement","Settlement_Date","UTR","Action","Match_Method"]]


def load_payment_matches(data_dir, master):
    matches=[]; unmatched=[]
    # PayU
    for src in ["PayU Settlement - Glen","PayU Settlement - Alda"]:
        p=source_path(data_dir,src)
        if p.exists():
            d=read_excel(p)
            m=_match_by_payment(master,d,"Merchant Txn ID",src,"Amount","Net Amount","Settlement Date","Merchant UTR","Requested Action")
            matches.append(m)
            matched_ids=set(m["Order No"]) if not m.empty else set()
    # Snapmint
    p=source_path(data_dir,"Snapmint")
    if p.exists():
        d=read_excel(p)
        m=_match_by_payment(master,d,"Shopify Payment ID","Snapmint","Order value","Settlement Value","Merchant Settlement Date","UTR No.","settled_for")
        matches.append(m)
    # Razorpay: order_receipt contains Shopify order no or payment id
    p=source_path(data_dir,"Razorpay")
    if p.exists():
        d=read_excel(p)
        lookup_order={norm_order(x):norm_order(x) for x in master["Order No"]}
        payment_to_order={norm_id(r["Payment ID"]):r["Order No"] for _,r in master.iterrows() if norm_id(r["Payment ID"])}
        rows=[]; unmatched_rows=[]
        for _,r in d.iterrows():
            candidates=[clean_str(r.get("order_receipt")),clean_str(r.get("payment_notes")),clean_str(r.get("order_notes"))]
            order=""; method=""
            for c in candidates:
                no=norm_order(c)
                if no in lookup_order: order=no; method="Razorpay receipt/order note → Shopify Order No"; break
                for pid,ono in payment_to_order.items():
                    if pid and pid in c: order=ono; method="Razorpay note → Shopify Payment ID"; break
                if order: break
            if order:
                rows.append({"Order No":order,"Gateway":"Razorpay","Txn_Amount":float(pd.to_numeric(r.get("amount"),errors="coerce") or 0),
                    "Net_Settlement":float(pd.to_numeric(r.get("credit"),errors="coerce") or 0),
                    "Settlement_Date":pd.to_datetime(r.get("settled_at"),errors="coerce"),"UTR":clean_str(r.get("settlement_utr")),
                    "Action":clean_str(r.get("transaction_entity")),"Match_Method":method})
            else: unmatched_rows.append(r)
        matches.append(pd.DataFrame(rows))
        if unmatched_rows: unmatched.append(("Razorpay",pd.DataFrame(unmatched_rows)))
    # Paytm / QR kept as unmatched unless direct Shopify reference is available
    for src in ["Paytm Gateway","Paytm QR"]:
        p=source_path(data_dir,src)
        if p.exists():
            d=read_excel(p)
            pay_to_order={norm_id(r["Payment ID"]):r["Order No"] for _,r in master.iterrows() if norm_id(r["Payment ID"])}
            ordset=set(master["Order No"])
            rows=[]; um=[]
            candidate_cols=[c for c in ["order_id","merchant_unique_ref","merchant_ref_id","reference_no","comments","udf1","udf2","udf3"] if c in d]
            for _,r in d.iterrows():
                order=""; method=""
                joined=" | ".join(clean_str(r.get(c)) for c in candidate_cols)
                no=norm_order(joined)
                if no in ordset: order=no; method=f"{src} reference → Shopify Order No"
                if not order:
                    for pid,ono in pay_to_order.items():
                        if pid and pid in joined: order=ono; method=f"{src} reference → Shopify Payment ID"; break
                if order:
                    rows.append({"Order No":order,"Gateway":src,"Txn_Amount":float(pd.to_numeric(r.get("amount"),errors="coerce") or 0),
                        "Net_Settlement":float(pd.to_numeric(r.get("settled_amount"),errors="coerce") or 0),
                        "Settlement_Date":pd.to_datetime(r.get("settled_date"),errors="coerce"),"UTR":clean_str(r.get("utr_no")),
                        "Action":clean_str(r.get("transaction_type")),"Match_Method":method})
                else: um.append(r)
            matches.append(pd.DataFrame(rows));
            if um: unmatched.append((src,pd.DataFrame(um)))
    # Mobikwik - typically QR; keep unmatched unless Shopify reference appears
    p=source_path(data_dir,"Mobikwik")
    if p.exists():
        d=read_excel(p,sheet_name="Report")
        unmatched.append(("Mobikwik",d))
    allm=pd.concat([m for m in matches if m is not None and not m.empty],ignore_index=True) if any(m is not None and not m.empty for m in matches) else pd.DataFrame(columns=["Order No","Gateway","Txn_Amount","Net_Settlement","Settlement_Date","UTR","Action","Match_Method"])
    return allm, unmatched


def aggregate_payments(m):
    if m.empty: return pd.DataFrame(columns=["Order No"])
    x=m.copy()
    action=x["Action"].astype(str).str.lower()
    refund=action.str.contains("refund|cancel|debit")
    x["Collection"] = np.where(refund,0,x["Txn_Amount"])
    x["Refund"] = np.where(refund,x["Txn_Amount"].abs(),0)
    x["Settlement"] = x["Net_Settlement"]
    g=x.groupby("Order No")
    out=g.agg(Gateway_Collection=("Collection","sum"),Gateway_Refund=("Refund","sum"),Gateway_Settlement=("Settlement","sum"),Last_Settlement_Date=("Settlement_Date","max")).reset_index()
    out=out.merge(g["Gateway"].apply(lambda s:", ".join(dict.fromkeys([clean_str(v) for v in s if clean_str(v)]))).rename("Matched_Gateway"),on="Order No",how="left")
    out=out.merge(g["UTR"].apply(lambda s:", ".join(dict.fromkeys([clean_str(v) for v in s if clean_str(v)]))).rename("Settlement_UTR"),on="Order No",how="left")
    out=out.merge(g["Match_Method"].apply(lambda s:" | ".join(dict.fromkeys([clean_str(v) for v in s if clean_str(v)]))).rename("Match_Method"),on="Order No",how="left")
    return out


def build_control_tower(data_dir):
    raw=load_shopify(data_dir); master=aggregate_shopify(raw)
    if master.empty: return master, pd.DataFrame(), [], raw
    sales=aggregate_sales(load_sales(data_dir))
    matches, unmatched=load_payment_matches(data_dir,master)
    pay=aggregate_payments(matches)
    ct=master.merge(sales,on="Order No",how="left").merge(pay,on="Order No",how="left")
    for c in ["Invoice_Value","Invoice_Qty","CN_Value","Gateway_Collection","Gateway_Refund","Gateway_Settlement"]:
        if c not in ct: ct[c]=0
        ct[c]=num(ct[c])
    ct["Order Status"]=np.where(ct["Cancelled at"].notna(),"Cancelled","Active")
    fs=ct["Fulfillment Status"].fillna("").astype(str).str.lower()
    ct["Fulfilment Status"]=np.select([fs.eq("fulfilled"),fs.str.contains("partial")],["Fulfilled","Partially Fulfilled"],default="Unfulfilled")
    ct["Billing Status"]=np.where(ct["Invoice_Value"]<=0,"Unbilled",np.where((ct["Invoice_Value"]+1)<ct["Total"],"Partially Billed","Billed"))
    fin=ct["Financial Status"].fillna("").astype(str).str.lower()
    ct["Payment Status"]=np.select([fin.isin(["paid","partially_refunded","refunded"]),ct["Gateway_Collection"]>0,fin.str.contains("pending")],["Payment Received","Payment Received","Payment Pending"],default="Payment Pending")
    refunded=ct["Refunded Amount"].fillna(0)
    ct["Refund Status"]=np.where(refunded<=0,"No Refund",np.where(refunded+1>=ct["Total"],"Refunded","Partially Refunded"))
    has_settlement=(ct["Gateway_Settlement"].abs()>0)|(ct["Settlement_UTR"].fillna("").astype(str)!="")
    needs_settlement=ct["Payment Method"].fillna("").astype(str).str.lower().str.contains("payu|razor|snapmint|paytm|mobikwik|wallet|card|upi")
    ct["Settlement Status"]=np.select([~needs_settlement,has_settlement],["Not Applicable","Settled"],default="Unsettled")
    ct["CN Status"]=np.where(ct["CN_Value"]>0,"CN Issued",np.where((ct["Refunded Amount"]>0)|(ct["Order Status"].eq("Cancelled")&ct["Invoice_Value"].gt(0)),"CN Required / Check","Not Required"))
    ct["Settlement Difference"]=(ct["Gateway_Collection"]-ct["Gateway_Refund"]-ct["Gateway_Settlement"]).round(2)
    reasons=[]
    for _,r in ct.iterrows():
        rr=[]
        if r["Order Status"]=="Active" and r["Fulfilment Status"]=="Fulfilled" and r["Billing Status"]=="Unbilled": rr.append("Fulfilled but unbilled")
        if r["Order Status"]=="Cancelled" and r["Invoice_Value"]>0: rr.append("Cancelled but invoice exists")
        if r["Refunded Amount"]>0 and r["CN_Status"] if False else False: pass
        if r["Payment Status"]=="Payment Received" and r["Settlement Status"]=="Unsettled" and needs_settlement.loc[_]: rr.append("Payment received but unsettled")
        if r["Refunded Amount"]>0 and r["CN Status"]!="CN Issued": rr.append("Refund/Cancellation needs CN check")
        if abs(r["Settlement Difference"])>5 and r["Gateway_Collection"]>0: rr.append("Settlement difference")
        reasons.append("; ".join(rr))
    ct["Exception Reason"]=reasons
    ct["Final Closure"]=np.where(ct["Exception Reason"].ne(""),"Action Required",np.where((ct["Order Status"].eq("Cancelled"))|((ct["Billing Status"].eq("Billed"))&(ct["Fulfilment Status"].eq("Fulfilled"))&(ct["Settlement Status"].isin(["Settled","Not Applicable"]))),"Closed","Open"))
    ct["Order Age Days"]=(pd.Timestamp.today().normalize()-pd.to_datetime(ct["Created at"],errors="coerce")).dt.days
    cols=["Order No","Created at","Billing Name","Email","Total","Order Qty","SKUs","Payment Method","Financial Status","Order Status","Fulfilment Status","Billing Status","Invoice_No","Invoice_Date","Invoice_Value","CN Status","CN_Value","Payment Status","Matched_Gateway","Gateway_Collection","Gateway_Refund","Gateway_Settlement","Settlement Status","Last_Settlement_Date","Settlement_UTR","Settlement Difference","Refund Status","Refunded Amount","Outstanding Balance","Final Closure","Exception Reason","Match_Method","Products"]
    cols=[c for c in cols if c in ct.columns]
    return ct[cols].sort_values("Created at",ascending=False), matches, unmatched, raw
