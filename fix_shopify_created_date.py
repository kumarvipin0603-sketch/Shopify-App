from pathlib import Path
import shutil
from datetime import datetime
import py_compile
import sys

p = Path("reconciliation.py")
if not p.exists():
    print("ERROR: reconciliation.py not found in current folder.")
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = p.with_name(f"reconciliation_backup_datefix_{stamp}.py")
shutil.copy2(p, backup)
print(f"Backup created: {backup.name}")

text = p.read_text(encoding="utf-8")

old = """    for c in [\\"Created at\\",\\"Paid at\\",\\"Fulfilled at\\",\\"Cancelled at\\"]:
        if c in df: df[c] = pd.to_datetime(df[c], errors=\\"coerce\\", utc=True).dt.tz_convert(None)
"""
new = """    # Convert Shopify timestamps to India local time before dropping timezone.
    for c in [\\"Created at\\",\\"Paid at\\",\\"Fulfilled at\\",\\"Cancelled at\\"]:
        if c in df:
            df[c] = (
                pd.to_datetime(df[c], errors=\\"coerce\\", utc=True)
                .dt.tz_convert(\\"Asia/Kolkata\\")
                .dt.tz_localize(None)
            )
"""

if old not in text:
    if '.dt.tz_convert("Asia/Kolkata")' in text:
        print("Date fix already present.")
    else:
        print("ERROR: Expected old datetime block not found; file was not changed.")
        sys.exit(2)
else:
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")
    print("Created/Paid/Fulfilled/Cancelled date timezone fix applied.")

py_compile.compile(str(p), doraise=True)
print("reconciliation.py compile check: OK")
print()
print("Now restart Streamlit:")
print("py -m streamlit run app.py")
