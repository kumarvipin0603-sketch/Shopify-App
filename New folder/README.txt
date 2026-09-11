GLEN WEBSITE ORDER CONTROL TOWER

1. Extract the ZIP to any folder.
2. Double-click run_local.bat.
3. The first run installs Streamlit and required Python packages.
4. Browser opens automatically at http://localhost:8501
5. Use Upload Centre to replace/update each source independently.

CURRENT PRELOADED SOURCES
- Shopify Orders
- Sale Register
- PayU Glen
- PayU Alda
- Razorpay
- Snapmint
- Mobikwik
- Paytm Gateway
- Paytm QR

PENDING SOURCES / UPLOAD-READY
- Website Team Update
- Paytm Wallet
- Delhivery
- Bluedart
- GVV

IMPORTANT MATCHING RULES IN V1
- Shopify Order No <-> Sale Register MSD Po Number
- Shopify Payment ID/Reference <-> PayU Merchant Txn ID
- Shopify Payment ID <-> Snapmint Shopify Payment ID
- Razorpay order_receipt / notes are checked for Shopify Order No or Payment ID
- Paytm and Mobikwik are not force-matched when no reliable Shopify reference exists; they remain visible under unmatched gateway rows.

This prevents false reconciliation. Website Team Update/logistics parsers can be added when those exact files are supplied.
