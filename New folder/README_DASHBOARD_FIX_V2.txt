Dashboard Comparison Fix V2

What was corrected:
1. Sale Register reads only active row-preserving snapshot keys (sale-row:...) from Neon when those snapshot rows exist.
2. Legacy Sale Register business-key rows are ignored during database-to-local sync so they cannot duplicate Invoice/CN totals.
3. Source Health counts the active Sale Register snapshot rather than legacy + snapshot rows.
4. Fixed psycopg2 percent escaping in Sale Register snapshot cleanup for future Sale Register uploads.
5. Dashboard comparison logic from previous version remains unchanged:
   - Shopify Orders basis -> Shopify Created at controls order set; MSD values only for those orders.
   - MSD basis -> MSD Invoice Date controls rows and direct MSD Invoice/CN values.

Validation against bundled MSD data for 01-Apr-2026 to 30-Jun-2026:
Invoice rows: 5,302
Invoice Value: 45,522,117.98
Credit Memo rows: 893
CN Value: 7,232,931.98
Unique invoice PO numbers: 4,917
