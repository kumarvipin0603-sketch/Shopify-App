from pathlib import Path
import shutil
from datetime import datetime
import py_compile
import re
import sys

p = Path("reconciliation.py")
if not p.exists():
    print("ERROR: reconciliation.py not found in current folder.")
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = p.with_name(f"reconciliation_backup_datefix2_{stamp}.py")
shutil.copy2(p, backup)
print(f"Backup created: {backup.name}")

text = p.read_text(encoding="utf-8")

pattern = re.compile(
    r'(?ms)^([ \t]*)for c in \["Created at","Paid at","Fulfilled at","Cancelled at"\]:\s*\n'
    r'\1[ \t]*if c in df:\s*df\[c\]\s*=\s*pd\.to_datetime\(df\[c\],\s*errors="coerce",\s*utc=True\)\.dt\.tz_convert\(None\)'
)

replacement = '''\\1for c in ["Created at","Paid at","Fulfilled at","Cancelled at"]:
\\1    if c in df:
\\1        df[c] = (
\\1            pd.to_datetime(df[c], errors="coerce", utc=True)
\\1            .dt.tz_convert("Asia/Kolkata")
\\1            .dt.tz_localize(None)
\\1        )'''

new_text, count = pattern.subn(replacement, text, count=1)

if count == 0:
    pattern2 = re.compile(
        r'(?ms)^([ \t]*)for c in \[\s*"Created at"\s*,\s*"Paid at"\s*,\s*"Fulfilled at"\s*,\s*"Cancelled at"\s*\]:\s*\n'
        r'\1[ \t]*if c in df:\s*df\[c\]\s*=\s*pd\.to_datetime\(\s*df\[c\]\s*,\s*errors\s*=\s*"coerce"\s*,\s*utc\s*=\s*True\s*\)\.dt\.tz_convert\(\s*None\s*\)'
    )
    new_text, count = pattern2.subn(replacement, text, count=1)

if count == 0:
    if '.dt.tz_convert("Asia/Kolkata")' in text:
        print("Date fix is already present; no change needed.")
    else:
        print("ERROR: Could not locate the Shopify datetime conversion block.")
        print("No file changes were made.")
        sys.exit(2)
else:
    p.write_text(new_text, encoding="utf-8")
    print("Shopify Created/Paid/Fulfilled/Cancelled timestamps now use Asia/Kolkata.")

py_compile.compile(str(p), doraise=True)
print("reconciliation.py compile check: OK")

print()
print("Verification command:")
print('findstr /N /C:"Asia/Kolkata" reconciliation.py')
print()
print("Then restart:")
print("py -m streamlit run app.py")
