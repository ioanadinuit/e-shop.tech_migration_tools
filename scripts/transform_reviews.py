"""
Transform PrestaShop product comments (reviews) into SQL INSERTs for the
e-shop.tech `product_feedback` table.

Input: CSV from sql/presta/05-product-reviews.sql, columns:
  product_reference, customer_name, customer_email, rating, comment, title, date_add, date_upd

Output:
  product_feedback.sql  — INSERT statements that resolve user_id by email and
                          product_id by code, skipping rows where lookup fails.

Why SQL and not CSV upload:
  e-shop.tech does not have an admin CSV upload for product_feedback.
  Direct INSERTs are the cleanest path.

The platform's product_feedback table has UNIQUE(user_id, product_id), so a
user can have at most one review per product. If the Presta data has multiple
comments per (customer, product), the script keeps only the latest by date_add.

Usage:
  python scripts/transform_reviews.py --reviews-csv ./exports/reviews.csv --out ./ready
"""
import argparse
import csv
import os
import sys
from datetime import datetime


csv.field_size_limit(2**31 - 1)


def _sql_escape(s):
    if s is None:
        return "NULL"
    s = str(s).replace("'", "''")
    return f"'{s}'"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--reviews-csv", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)

    with open(args.reviews_csv, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"[reviews] {len(rows)} rows read")

    # Dedup by (email, product_reference) keeping latest by date_add.
    latest = {}
    for r in rows:
        key = ((r.get("customer_email") or "").strip().lower(),
               (r.get("product_reference") or "").strip())
        if not all(key):
            continue
        date = r.get("date_add", "") or ""
        if key not in latest or date > latest[key].get("date_add", ""):
            latest[key] = r

    skipped_no_grade = 0
    sql_path = os.path.join(args.out, "product_feedback.sql")
    with open(sql_path, "w", encoding="utf-8") as f:
        f.write("-- Migrated product reviews from PrestaShop.\n")
        f.write("-- Resolves user_id by email and product_id by code.\n")
        f.write("-- Rows where either lookup fails are silently dropped (cross-checked count below).\n\n")
        for (email, ref), r in latest.items():
            try:
                rating = float(r.get("rating") or 0)
            except (TypeError, ValueError):
                rating = 0
            if rating <= 0:
                skipped_no_grade += 1
                continue
            rating = round(rating)  # platform expects integer 1-5

            comment = (r.get("comment") or "").strip()
            title = (r.get("title") or "").strip()
            full_comment = f"{title}\n\n{comment}" if title and title.strip() else comment
            date_add = r.get("date_add") or ""

            f.write(
                "INSERT INTO product_feedback (user_id, product_id, rating, comment, created_at)\n"
                "SELECT u.user_id, p.product_id, "
                f"{rating}, {_sql_escape(full_comment)}, {_sql_escape(date_add)}\n"
                f"FROM \"user\" u, product p\n"
                f"WHERE u.email = {_sql_escape(email)} AND p.code = {_sql_escape(ref)}\n"
                "ON CONFLICT (user_id, product_id) DO NOTHING;\n\n"
            )

    print(f"[reviews] -> product_feedback.sql ({len(latest) - skipped_no_grade} INSERTs, "
          f"{skipped_no_grade} skipped for missing rating)")
    print(f"[reviews] Note: rows whose email or reference do not match a row in user/product")
    print(f"          tables on the new platform are silently skipped via the SELECT/JOIN.")


if __name__ == "__main__":
    main()
