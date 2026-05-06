"""
Transform PrestaShop product comments (reviews) into SQL INSERTs for the
e-shop.tech `product_feedback` table.

Input: CSV from sql/presta/05-product-reviews.sql, columns:
  product_reference, customer_name, customer_email, rating, comment, title, date_add

Output:
  product_feedback.sql  — INSERT statements with two paths:
    - authenticated reviewer: row has @-email → resolve user_id by email;
      uses ON CONFLICT to be idempotent
    - guest reviewer: row has no real email → store as guest_name +
      guest_origin = 'migrated_presta', user_id = NULL
  Both paths resolve product_id by reference (= product.code).

Why SQL and not CSV upload:
  e-shop.tech does not have an admin CSV upload for product_feedback.
  Direct INSERTs are the cleanest path.

Usage:
  python scripts/transform_reviews.py --reviews-csv ./exports/reviews.csv --out ./ready
"""
import argparse
import csv
import os
import sys


csv.field_size_limit(2**31 - 1)


def _sql_escape(s):
    if s is None:
        return "NULL"
    s = str(s).replace("'", "''")
    return f"'{s}'"


def _is_real_email(s):
    if not s:
        return False
    s = s.strip().lower()
    return s and s != "null" and "@" in s and "." in s


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--reviews-csv", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--guest-origin", default="migrated_presta",
                   help="Value for product_feedback.guest_origin on guest rows")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)

    with open(args.reviews_csv, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"[reviews] {len(rows)} rows read")

    # Bucket rows into two paths and dedup each appropriately.
    #  - authed: dedup by (email, product_reference) keeping latest — UNIQUE
    #            constraint on (user_id, product_id) requires this.
    #  - guest:  dedup by (customer_name, product_reference) keeping latest —
    #            no DB constraint forces this but we still don't want the
    #            same name to flood reviews on the same product post-migration.
    authed = {}     # (email, ref) -> row
    guests = {}     # (guest_name, ref) -> row

    for r in rows:
        ref = (r.get("product_reference") or "").strip()
        if not ref:
            continue
        date = r.get("date_add") or ""
        email = (r.get("customer_email") or "").strip().lower()
        name = (r.get("customer_name") or "").strip()

        if _is_real_email(email):
            key = (email, ref)
            if key not in authed or date > (authed[key].get("date_add") or ""):
                authed[key] = r
        elif name:
            key = (name, ref)
            if key not in guests or date > (guests[key].get("date_add") or ""):
                guests[key] = r
        # rows with neither email nor name are unattributable — drop

    print(f"[reviews] {len(authed)} authed reviews + {len(guests)} guest reviews after dedup")

    skipped_no_grade = 0
    sql_path = os.path.join(args.out, "product_feedback.sql")
    with open(sql_path, "w", encoding="utf-8") as f:
        f.write("-- Migrated product reviews from PrestaShop.\n")
        f.write("-- Authed path: resolve user_id by email + product_id by code.\n")
        f.write("-- Guest path:  user_id = NULL, store customer_name as guest_name.\n")
        f.write("-- Rows whose product_reference doesn't match a row in product\n")
        f.write("-- table are silently skipped via the SELECT/JOIN.\n\n")
        f.write("BEGIN;\n\n")

        # ── Authed reviews ─────────────────────────────────────────────────
        for (email, ref), r in authed.items():
            try:
                rating = float(r.get("rating") or 0)
            except (TypeError, ValueError):
                rating = 0
            if rating <= 0:
                skipped_no_grade += 1
                continue
            rating = round(rating)

            comment = (r.get("comment") or "").strip()
            title = (r.get("title") or "").strip()
            full_comment = f"{title}\n\n{comment}" if title else comment
            date_add = r.get("date_add") or ""

            f.write(
                "INSERT INTO product_feedback (user_id, product_id, grade, comment, created_at, display, moderated)\n"
                "SELECT u.user_id, p.product_id, "
                f"{rating}, {_sql_escape(full_comment)}, {_sql_escape(date_add)}, TRUE, TRUE\n"
                'FROM "user" u, product p\n'
                f"WHERE u.email = {_sql_escape(email)} AND p.code = {_sql_escape(ref)}\n"
                "ON CONFLICT (user_id, product_id) DO NOTHING;\n\n"
            )

        # ── Guest reviews ──────────────────────────────────────────────────
        for (name, ref), r in guests.items():
            try:
                rating = float(r.get("rating") or 0)
            except (TypeError, ValueError):
                rating = 0
            if rating <= 0:
                skipped_no_grade += 1
                continue
            rating = round(rating)

            comment = (r.get("comment") or "").strip()
            title = (r.get("title") or "").strip()
            full_comment = f"{title}\n\n{comment}" if title else comment
            date_add = r.get("date_add") or ""

            f.write(
                "INSERT INTO product_feedback (user_id, product_id, grade, comment, created_at, "
                "display, moderated, guest_name, guest_origin)\n"
                "SELECT NULL, p.product_id, "
                f"{rating}, {_sql_escape(full_comment)}, {_sql_escape(date_add)}, TRUE, TRUE, "
                f"{_sql_escape(name)}, {_sql_escape(args.guest_origin)}\n"
                "FROM product p\n"
                f"WHERE p.code = {_sql_escape(ref)};\n\n"
            )

        f.write("COMMIT;\n")

    total = len(authed) + len(guests) - skipped_no_grade
    print(f"[reviews] -> product_feedback.sql ({total} INSERTs, {skipped_no_grade} skipped for missing rating)")


if __name__ == "__main__":
    main()
