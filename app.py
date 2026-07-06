import os
import sqlite3
import datetime
import secrets
import re
from functools import wraps

import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)

# SECRET_KEY signs the admin session cookie — set a real one via Render's
# environment variables. Falls back to a random key on each restart if unset,
# which just means admins get logged out on redeploy (fine for this scale).
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# Admin credentials come from environment variables — never hardcode these.
# Set both in Render's dashboard under Environment.
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")  # no default on purpose

# NOTE on Render's free tier: the filesystem is ephemeral. This SQLite file
# persists fine while the service is running, but a redeploy or a spin-down
# (free services sleep after inactivity) can wipe it. That's fine for a demo/
# portfolio project. If you need logs to survive long-term, see the README
# section on adding a persistent database.
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "visitors.db"))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            country TEXT,
            region TEXT,
            city TEXT,
            isp TEXT,
            browser TEXT,
            os TEXT,
            device TEXT,
            user_agent_raw TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", request.remote_addr)
    if forwarded and "," in forwarded:
        forwarded = forwarded.split(",")[0].strip()
    return forwarded


def lookup_geo(ip):
    """Best-effort geolocation. Fails silently (returns Unknowns) so a slow or
    down third-party API never breaks the page for a real visitor."""
    private_prefixes = ("127.", "10.", "192.168.", "::1")
    if not ip or ip.startswith(private_prefixes):
        return {"country": "Local/Private", "region": "-", "city": "-", "isp": "-"}
    try:
        r = requests.get(f"https://ipapi.co/{ip}/json/", timeout=2.5)
        data = r.json()
        if data.get("error"):
            raise ValueError("api error")
        return {
            "country": data.get("country_name") or "Unknown",
            "region": data.get("region") or "Unknown",
            "city": data.get("city") or "Unknown",
            "isp": data.get("org") or "Unknown",
        }
    except Exception:
        return {"country": "Unknown", "region": "Unknown", "city": "Unknown", "isp": "Unknown"}


def parse_device(user_agent_string):
    """Lightweight User-Agent parsing — no external dependency required.
    Not as exhaustive as a dedicated library, but covers the vast majority
    of real traffic (Chrome/Safari/Firefox/Edge on Windows/Mac/Android/iOS)."""
    ua = user_agent_string or ""
    ua_lower = ua.lower()

    # device type
    if "tablet" in ua_lower or "ipad" in ua_lower:
        device = "Tablet"
    elif "mobi" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        device = "Mobile"
    elif ua:
        device = "Desktop"
    else:
        device = "Unknown"

    # operating system
    os_patterns = [
        (r"windows nt 10", "Windows 10/11"),
        (r"windows nt 6\.3", "Windows 8.1"),
        (r"windows nt 6\.1", "Windows 7"),
        (r"mac os x (\d+[_\.]\d+)", "macOS"),
        (r"android (\d+(\.\d+)?)", "Android"),
        (r"iphone os (\d+[_\.]\d+)", "iOS"),
        (r"ipad.*os (\d+[_\.]\d+)", "iPadOS"),
        (r"linux", "Linux"),
    ]
    os_name = "Unknown"
    for pattern, label in os_patterns:
        m = re.search(pattern, ua_lower)
        if m:
            os_name = label
            break

    # browser
    browser_patterns = [
        (r"edg/([\d.]+)", "Edge"),
        (r"opr/([\d.]+)", "Opera"),
        (r"chrome/([\d.]+)", "Chrome"),
        (r"crios/([\d.]+)", "Chrome (iOS)"),
        (r"firefox/([\d.]+)", "Firefox"),
        (r"version/([\d.]+).*safari", "Safari"),
    ]
    browser = "Unknown"
    for pattern, label in browser_patterns:
        m = re.search(pattern, ua_lower)
        if m:
            browser = f"{label} {m.group(1)}"
            break

    return browser, os_name, device


def save_visit(ip, geo, browser, os_name, device, raw_ua):
    conn = get_db()
    conn.execute(
        """INSERT INTO visits (ip, country, region, city, isp, browser, os, device, user_agent_raw, timestamp)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            ip, geo["country"], geo["region"], geo["city"], geo["isp"],
            browser, os_name, device, raw_ua,
            datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        ),
    )
    conn.commit()
    conn.close()


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


# --------------------------------------------------------------- routes ----

@app.route("/")
def home():
    visitor_ip = get_client_ip()
    raw_ua = request.headers.get("User-Agent", "")
    geo = lookup_geo(visitor_ip)
    browser, os_name, device = parse_device(raw_ua)
    save_visit(visitor_ip, geo, browser, os_name, device, raw_ua)
    return render_template("index.html", ip_address=visitor_ip, geo=geo, browser=browser, os_name=os_name, device=device)


@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if not ADMIN_PASSWORD:
            flash("Server misconfigured: ADMIN_PASSWORD environment variable is not set.")
            return render_template("admin_login.html")

        # secrets.compare_digest avoids timing-attack shortcuts on the check
        valid = secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD)
        if valid:
            session["is_admin"] = True
            return redirect(url_for("admin_panel"))
        flash("Incorrect username or password.")
    return render_template("admin_login.html")


@app.route("/admin-logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin-panel")
@admin_required
def admin_panel():
    conn = get_db()
    rows = conn.execute("SELECT * FROM visits ORDER BY id DESC LIMIT 500").fetchall()
    total = conn.execute("SELECT COUNT(*) as c FROM visits").fetchone()["c"]
    conn.close()
    return render_template("admin_panel.html", visits=rows, total=total)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
else:
    init_db()
