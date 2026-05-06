"""
One-shot: re-normalize first_name / last_name on already-imported users.

Reads the same customers CSV that transform_users.py consumed, runs the
exact same _normalize_name on firstname/lastname, and emits UPDATE
statements keyed by email. Safe to run after the initial import without
touching authentication, role, user_address, or product_feedback rows.

Usage:
  python scripts/fix_user_names.py --customers-csv ./exports/customers.csv --out ./ready
  Get-Content ./ready/fix_user_names.sql -Raw | docker exec -i postgres psql -U postgres -d eshop
"""
import argparse
import csv
import os

from transform_users import _normalize_name, _sql_escape


csv.field_size_limit(2**31 - 1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--customers-csv", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)

    with open(args.customers_csv, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    # Same dedup as transform_users.py — keep latest per email
    by_email = {}
    for r in rows:
        email = (r.get("email") or "").strip().lower()
        if not email:
            continue
        if email not in by_email or (r.get("updated_at") or "") > (by_email[email].get("updated_at") or ""):
            by_email[email] = r

    out_path = os.path.join(args.out, "fix_user_names.sql")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("-- Re-normalize migrated user names (mojibake strip + title-case).\n")
        f.write("BEGIN;\n\n")
        for email, r in by_email.items():
            first = _normalize_name(r.get("firstname"))
            last = _normalize_name(r.get("lastname"))
            if not first and not last:
                continue
            f.write(
                f'UPDATE "user" SET first_name = {_sql_escape(first)}, '
                f'last_name = {_sql_escape(last)} '
                f"WHERE email = {_sql_escape(email)};\n"
            )
        f.write("\nCOMMIT;\n")

    print(f"-> {out_path} ({len(by_email)} updates)")


if __name__ == "__main__":
    main()
