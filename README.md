# Visitor Dashboard + Admin Panel

Logs each visitor's IP, approximate location, browser, OS, and device type
to a local SQLite database, viewable through a password-protected admin
panel at `/admin-panel`.

## What's new vs. your original version

1. **SQLite instead of a flat text file** — much easier to query, sort, and
   display in a table.
2. **`/admin-panel`** — password-protected page showing all logged visits
   in a sortable table. Login at `/admin-login`.
3. **Extra visitor info** — country/region/city/ISP (via ipapi.co) and
   browser/OS/device type (parsed from the User-Agent header, no external
   library needed).

## Environment variables (set these — don't hardcode passwords)

| Variable | Required | Purpose |
|---|---|---|
| `ADMIN_USERNAME` | No (defaults to `admin`) | Admin panel login username |
| `ADMIN_PASSWORD` | **Yes** | Admin panel login password — app refuses login attempts if unset |
| `SECRET_KEY` | Recommended | Signs the admin session cookie. If unset, a random one is generated each restart, which just logs admins out on redeploy — not a big deal, but set a real one for consistency |
| `DB_PATH` | No | Override where the SQLite file is stored (see filesystem note below) |

**On Render:** Dashboard → your service → Environment → Add Environment
Variable, for each of the above. Generate a strong `ADMIN_PASSWORD` — this
page will be reachable by anyone who guesses the URL, so don't use
something simple.

## Running locally (Termux or anywhere)

```
pip install -r requirements.txt
ADMIN_USERNAME=admin ADMIN_PASSWORD=your-real-password python app.py
```

Visit `http://localhost:5000` for the visitor page, and
`http://localhost:5000/admin-panel` for the dashboard (redirects to login
first).

## Deploying to Render

1. Push this folder to a GitHub repo (or connect Render directly to your
   existing repo).
2. Render dashboard → **New → Web Service** → connect the repo.
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `gunicorn app:app`
5. Add the environment variables from the table above.
6. Deploy.

## Important: Render's free-tier filesystem is ephemeral

This matters a lot for a project whose whole point is logging data:

- The SQLite file (`visitors.db`) lives on the container's local disk.
- That disk **persists while the service is running**, so visits logged
  during a session are all there and queryable.
- But: Render's free web services **spin down after ~15 minutes of
  inactivity**, and free-tier redeploys can start a fresh container. Either
  event can wipe the SQLite file completely — you'd start back at zero
  visits.

**For a portfolio/demo project, this is fine** — it's expected behavior,
not a bug, and worth understanding rather than being surprised by later.

**If you need visit history to actually survive long-term**, you have two
real options:

1. **Render persistent disk** (paid, from ~$1/mo for 1GB) — mounts a real
   disk that survives restarts/redeploys. Just change `DB_PATH` to point
   inside the mounted disk path Render gives you.
2. **External database** (often free) — e.g. a free Postgres instance on
   [Supabase](https://supabase.com) or [Neon](https://neon.tech). This
   means swapping the `sqlite3` calls in `app.py` for a Postgres client
   (`psycopg2` or similar) — a bigger change, but the right one if this
   becomes more than a demo. Happy to help you make that swap when you're
   ready.

## Privacy note

Logging visitor IPs and rough location is standard practice (basically
what server access logs do automatically), but if this goes on a site with
real visitors, it's good practice to mention it in a short privacy note on
the site — one line like "We log visitor IP addresses and general location
for security and analytics" covers you without needing a full legal
document.
