DASHBOARD COMPARISON FIX
========================

What changed
------------
1. Dashboard now has a Comparison against selector:
   - Shopify Orders
   - MSD (Sale Register)

2. Shopify Orders basis
   - Date filter uses Shopify Created at.
   - Order count/value come from the selected Shopify orders.
   - Invoice and CN values are rebuilt directly from MSD rows whose Po Number
     exactly matches those selected Shopify order numbers.
   - Invoice/CN dates do not decide whether the order belongs to the period.

3. MSD basis
   - Date filter uses MSD Invoice Date.
   - Invoice Value is the sum of MSD Invoice Gross Amount in the selected period.
   - CN Value is SUM(ABS(Gross Amount)) for MSD credit/return/CN rows in the period.
   - Shopify details are attached only where MSD Po Number exactly matches a
     Shopify order number.

4. Reconciliation table
   - Shows order/PO level Shopify versus MSD values.
   - 'Show differences only' is enabled by default.
   - Flags: No MSD Invoice, MSD Invoice Higher, MSD Invoice Lower, MSD Only / Not in Shopify.

5. Strict MSD-to-Shopify matching
   - Only exact #<digits> MSD Po Number values are treated as Shopify orders.
   - Text such as PH26901-001 or NEFT PAYMENT ... is no longer converted into a
     false Shopify order number.

6. Date correctness
   - Shopify timestamps are converted to Asia/Kolkata before timezone removal.
   - DD-MM-YYYY settlement dates use dayfirst=True.

Validation against bundled Sale Register
----------------------------------------
MSD Invoice Date 01-Apr-2026 to 30-Jun-2026:
- Invoice Value: 45,522,117.98
- CN / Return Value: 7,232,931.98

Shopify Created at 01-Apr-2026 to 30-Jun-2026, then MSD lifecycle values only
for those selected Shopify order numbers:
- Invoice Value: 44,423,201.49
- CN Value: 6,519,587.89

These two views are intentionally different because the comparison basis and
its date field are different.
