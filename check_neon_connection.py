from pathlib import Path
import socket
import sys
from urllib.parse import urlparse

try:
    import streamlit as st
    import psycopg2
except Exception as e:
    print("ERROR importing required packages:", e)
    sys.exit(1)

print("=" * 72)
print("NEON CONNECTION CHECK")
print("=" * 72)

try:
    url = st.secrets["DATABASE_URL"]
except Exception as e:
    print("ERROR: DATABASE_URL could not be read from .streamlit/secrets.toml")
    print(e)
    sys.exit(2)

parsed = urlparse(url)
host = parsed.hostname
port = parsed.port or 5432
db = (parsed.path or "").lstrip("/") or "(unknown)"
user = parsed.username or "(unknown)"

print("Host :", host)
print("Port :", port)
print("DB   :", db)
print("User :", user)
print()

if not host:
    print("ERROR: Hostname is missing from DATABASE_URL.")
    sys.exit(3)

print("1) DNS lookup...")
try:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = sorted({x[4][0] for x in infos})
    print("   OK - resolved to:", ", ".join(ips))
except Exception as e:
    print("   FAILED - DNS could not resolve the Neon hostname.")
    print("   Error:", e)
    print()
    print("Run these Windows commands, then retry:")
    print("  ipconfig /flushdns")
    print(f"  nslookup {host}")
    print()
    print("If nslookup also fails, the issue is Windows/router/ISP DNS, not the app.")
    sys.exit(4)

print()
print("2) PostgreSQL connection...")
try:
    conn = psycopg2.connect(url, connect_timeout=15)
    cur = conn.cursor()
    cur.execute("SELECT 1")
    result = cur.fetchone()
    conn.close()
    print("   OK - Neon connection successful:", result)
except Exception as e:
    print("   FAILED - DNS works, but PostgreSQL connection failed.")
    print("   Error:", e)
    sys.exit(5)

print()
print("SUCCESS: DNS and Neon PostgreSQL are both working.")
print("Now restart Streamlit:")
print("  py -m streamlit run app.py")
