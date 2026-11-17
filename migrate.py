import os
import sys
import glob
import argparse
import psycopg2

from statmonitor.config import SUPABASE_DB_URL

DEFAULT_MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")

def get_db_connection(db_url=None):
    url = db_url or SUPABASE_DB_URL or os.environ.get("SUPABASE_DB_URL")
    if not url:
        return None, "SUPABASE_DB_URL не вказано."
    try:
        conn = psycopg2.connect(url, connect_timeout=10)
        return conn, None
    except Exception as e:
        return None, str(e)

def ensure_migrations_table(cur, conn):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    conn.commit()

def get_applied_migrations(cur):
    try:
        cur.execute("SELECT version, description, applied_at FROM schema_migrations ORDER BY version ASC;")
        return {r[0]: {"description": r[1], "applied_at": r[2]} for r in cur.fetchall()}
    except Exception:
        return {}

def get_migration_files(migrations_dir=None):
    target_dir = migrations_dir or DEFAULT_MIGRATIONS_DIR
    if not os.path.exists(target_dir):
        return []
    
    files = glob.glob(os.path.join(target_dir, "*.sql"))
    files.sort(key=lambda p: os.path.basename(p))

    parsed = []
    for f in files:
        bname = os.path.basename(f)
        parts = bname[:-4].split("_", 1)
        version = parts[0]
        desc = parts[1] if len(parts) > 1 else ""
        parsed.append({
            "version": version,
            "description": desc,
            "filename": bname,
            "path": f,
        })
    return parsed

def run_migrations(db_url=None, dry_run=False, migrations_dir=None):
    """
    Застосовує всі нові міграції із директорії migrations.
    Повертає список застосованих версій.
    """
    conn, err = get_db_connection(db_url)
    if not conn:
        print(f"❌ Помилка підключення до БД: {err}")
        return []

    applied_list = []
    try:
        cur = conn.cursor()
        ensure_migrations_table(cur, conn)
        already_applied = get_applied_migrations(cur)
        all_files = get_migration_files(migrations_dir)

        pending = [m for m in all_files if m["version"] not in already_applied]
        if not pending:
            print("✅ Всі міграції вже застосовані. База даних актуальна.")
            cur.close()
            conn.close()
            return []

        print(f"🚀 Знайдено нових міграцій: {len(pending)}")
        for m in pending:
            print(f"  ▶ Застосування [{m['version']}] {m['filename']}...")
            if dry_run:
                applied_list.append(m["version"])
                continue

            with open(m["path"], "r", encoding="utf-8") as f:
                sql = f.read()

            try:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version, description) VALUES (%s, %s);",
                    (m["version"], m["description"])
                )
                conn.commit()
                applied_list.append(m["version"])
                print(f"    ✔ Успішно застосовано [{m['version']}]")
            except Exception as me:
                conn.rollback()
                print(f"    ❌ Помилка виконання міграції {m['filename']}: {me}")
                raise me

        cur.close()
        conn.close()
        return applied_list
    except Exception as e:
        if conn:
            conn.close()
        print(f"❌ Зупинено через помилку: {e}")
        return applied_list

def show_status(db_url=None, migrations_dir=None):
    conn, err = get_db_connection(db_url)
    if not conn:
        print(f"❌ Помилка підключення: {err}")
        return

    cur = conn.cursor()
    ensure_migrations_table(cur, conn)
    applied = get_applied_migrations(cur)
    all_files = get_migration_files(migrations_dir)
    cur.close()
    conn.close()

    print("\n📦 Стан міграцій бази даних:")
    print("-" * 75)
    print(f"{'Версія':<10} | {'Файл':<35} | {'Статус':<15} | {'Дата'}")
    print("-" * 75)

    for m in all_files:
        v = m["version"]
        if v in applied:
            d_app = applied[v]["applied_at"]
            d_str = d_app.strftime("%Y-%m-%d %H:%M") if hasattr(d_app, "strftime") else str(d_app)[:16]
            status = "✔ Застосовано"
        else:
            status = "⏳ Очікує"
            d_str = "-"
        print(f"{v:<10} | {m['filename']:<35} | {status:<15} | {d_str}")
    print("-" * 75 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Міграційний раннер StatMonitor (SPEC-14)")
    parser.add_argument("--status", action="store_true", help="Показати статус міграцій")
    parser.add_argument("--dry-run", action="store_true", help="Симуляція без виконання")
    parser.add_argument("--url", type=str, default=None, help="Рядок підключення до БД")

    args = parser.parse_args()

    if args.status:
        show_status(db_url=args.url)
    else:
        applied = run_migrations(db_url=args.url, dry_run=args.dry_run)
        if applied:
            print(f"\n🎉 Успішно застосовано {len(applied)} міграцій: {', '.join(applied)}")
