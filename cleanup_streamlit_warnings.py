from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import re
import sys

APP = Path("app.py")
REC = Path("reconciliation.py")

for p in (APP, REC):
    if not p.exists():
        print(f"ERROR: {p} not found in the current folder.")
        sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backups = {}

def backup(path: Path):
    b = path.with_name(f"{path.stem}_backup_cleanup_{stamp}{path.suffix}")
    shutil.copy2(path, b)
    backups[path] = b
    print(f"Backup created: {b}")

backup(APP)
backup(REC)

try:
    # ------------------------------------------------------------------
    # 1) Fix empty st.radio label in app.py
    # ------------------------------------------------------------------
    app_text = APP.read_text(encoding="utf-8")
    original_app = app_text

    # Handles:
    # st.radio("", ...)
    # st.radio('', ...)
    # st.radio(
    #     "",
    #     ...
    radio_pattern = re.compile(
        r'(st\.radio\(\s*)(["\'])\s*\2(\s*,)',
        flags=re.MULTILINE
    )

    app_text, radio_count = radio_pattern.subn(
        r'\1"Navigation"\3',
        app_text,
        count=1
    )

    # If the radio now has a visible label and no label_visibility nearby,
    # add label_visibility="collapsed" before the closing call when we can
    # identify the page = st.radio(...) block.
    if radio_count:
        page_radio = re.search(
            r'(page\s*=\s*st\.radio\(\s*"Navigation"\s*,)(.*?)(\n\s*\))',
            app_text,
            flags=re.DOTALL
        )
        if page_radio and 'label_visibility=' not in page_radio.group(0):
            replacement = (
                page_radio.group(1)
                + page_radio.group(2).rstrip()
                + ',\n        label_visibility="collapsed"'
                + page_radio.group(3)
            )
            app_text = (
                app_text[:page_radio.start()]
                + replacement
                + app_text[page_radio.end():]
            )

    # ------------------------------------------------------------------
    # 2) Replace deprecated use_container_width in app.py
    # ------------------------------------------------------------------
    width_true_count = app_text.count("use_container_width=True")
    width_false_count = app_text.count("use_container_width=False")

    app_text = app_text.replace(
        "use_container_width=True",
        'width="stretch"'
    )
    app_text = app_text.replace(
        "use_container_width=False",
        'width="content"'
    )

    APP.write_text(app_text, encoding="utf-8")

    # ------------------------------------------------------------------
    # 3) Fix settlement date parsing in reconciliation.py
    # ------------------------------------------------------------------
    rec_text = REC.read_text(encoding="utf-8")

    # Exact compact form from the warning
    patterns = [
        (
            'pd.to_datetime(r.get("settled_date"),errors="coerce")',
            'pd.to_datetime(r.get("settled_date"), errors="coerce", dayfirst=True)'
        ),
        (
            'pd.to_datetime(r.get("settled_date"), errors="coerce")',
            'pd.to_datetime(r.get("settled_date"), errors="coerce", dayfirst=True)'
        ),
        (
            "pd.to_datetime(r.get('settled_date'),errors='coerce')",
            "pd.to_datetime(r.get('settled_date'), errors='coerce', dayfirst=True)"
        ),
        (
            "pd.to_datetime(r.get('settled_date'), errors='coerce')",
            "pd.to_datetime(r.get('settled_date'), errors='coerce', dayfirst=True)"
        ),
    ]

    date_count = 0
    for old, new in patterns:
        c = rec_text.count(old)
        if c:
            rec_text = rec_text.replace(old, new)
            date_count += c

    REC.write_text(rec_text, encoding="utf-8")

    # ------------------------------------------------------------------
    # Compile checks
    # ------------------------------------------------------------------
    py_compile.compile(str(APP), doraise=True)
    py_compile.compile(str(REC), doraise=True)

except Exception as e:
    print()
    print("ERROR:", e)
    print("Restoring original files...")
    for path, b in backups.items():
        shutil.copy2(b, path)
    print("Original files restored.")
    sys.exit(2)

print()
print("=" * 72)
print("CLEANUP PATCH RESULT")
print("=" * 72)
print(f"Empty radio label fixed       : {radio_count}")
print(f"use_container_width=True fixed: {width_true_count}")
print(f"use_container_width=False fixed: {width_false_count}")
print(f"Settlement date parser fixed  : {date_count}")
print("app.py compile check          : OK")
print("reconciliation.py compile     : OK")

if radio_count == 0:
    print()
    print("NOTE: No empty st.radio label was found automatically.")
    print("If the warning still appears, send the current app.py radio block.")

if date_count == 0:
    print()
    print("NOTE: No settled_date parser pattern was found automatically.")
    print("If the warning still appears, send the current reconciliation.py line 360.")

print()
print("Now restart Streamlit:")
print("  py -m streamlit run app.py")
