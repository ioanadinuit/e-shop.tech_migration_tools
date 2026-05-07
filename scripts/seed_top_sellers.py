"""
Seed a synthetic "legacy sales" order so the homepage's BEST_SELLER and
top-recommendations queries return a ranked list immediately after launch
— before any real orders accumulate.

Strategy:
  - One DELIVERED order, dated before launch, owned by an admin user.
  - 20 order_product rows with descending quantities (20, 19, ..., 1)
    so the ranking from biorganicbubu is preserved when the homepage
    sorts by sum(quantity) DESC.

Input:
  --codes-csv  CSV with a single column `code` listing 20 product codes
               in descending sales-rank order (top-1 first, top-20 last).
  --admin-email  Email of an admin user that already exists in the user
                 table; used as order.user_id.

Output:
  ./ready/top_sellers.sql — ready to pipe into psql.

Usage:
  python scripts/seed_top_sellers.py \\
      --codes-csv ./exports/biorganicbubu_top20.csv \\
      --admin-email admin@biotu.ro \\
      --out ./ready
"""
import argparse
import csv
import os


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--codes-csv", required=True)
    p.add_argument("--admin-email", required=True,
                   help="Admin user email — order.user_id will resolve from this.")
    p.add_argument("--out", required=True)
    p.add_argument("--target-count", type=int, default=20,
                   help="Take the top N existing codes (from DB join) and seed them. "
                        "If the CSV has 100 codes but only 30 exist in product table, "
                        "the seed picks the first 30 by CSV order, capped at this value.")
    p.add_argument("--order-date", default="2025-01-15 12:00:00",
                   help="Synthetic order created/last_modified timestamp (UTC).")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)

    with open(args.codes_csv, encoding="utf-8", newline="") as f:
        codes = [row["code"].strip() for row in csv.DictReader(f) if row.get("code", "").strip()]

    if not codes:
        raise SystemExit("[seed] no codes in CSV")
    if len(codes) > 500:
        raise SystemExit(f"[seed] too many codes ({len(codes)}); cap is 500 for safety")

    print(f"[seed] {len(codes)} top products to seed")

    sql_path = os.path.join(args.out, "top_sellers.sql")
    with open(sql_path, "w", encoding="utf-8") as f:
        f.write("-- Synthetic legacy-sales seed for homepage ranking.\n")
        f.write("-- Quantities descend so sum(quantity) DESC preserves the input order.\n")
        f.write("-- Idempotent: re-running first deletes any existing seed order so the\n")
        f.write("-- ranking always reflects the latest CSV.\n\n")
        f.write("BEGIN;\n\n")

        # Wipe any prior seed order (identified by a fixed marker in
        # other_details_message). Safer than guessing by date.
        f.write("DELETE FROM order_product WHERE order_id IN (\n")
        f.write("  SELECT order_id FROM \"order\" WHERE other_details_message = 'LEGACY_SEED_BIORGANICBUBU'\n")
        f.write(");\n")
        f.write("DELETE FROM \"order\" WHERE other_details_message = 'LEGACY_SEED_BIORGANICBUBU';\n\n")

        # Build the SQL in three CTEs:
        #   1. ranked_codes: every code from the CSV with its CSV order
        #      position (1 = top-1 by revenue, ...).
        #   2. matched: JOIN against product, drop missing codes, keep
        #      only the first <target-count> that survive the join,
        #      assign a fresh dense rank — that fresh rank drives
        #      the synthetic quantity.
        #   3. new_order: insert the wrapper order row and capture
        #      its order_id.
        # Then the final INSERT pulls product_id + price from `matched`
        # and uses (target_count - dense_rank + 1) as quantity so the
        # winning product gets the highest quantity.
        target = args.target_count
        f.write("WITH ranked_codes(code, csv_pos) AS (VALUES\n")
        for i, code in enumerate(codes):
            comma = "," if i < len(codes) - 1 else ""
            f.write(f"    ('{code.replace(chr(39), chr(39)*2)}', {i + 1}){comma}\n")
        f.write("),\n")
        f.write("matched AS (\n")
        f.write("    SELECT p.product_id, p.price,\n")
        f.write("           ROW_NUMBER() OVER (ORDER BY rc.csv_pos) AS rnk\n")
        f.write("    FROM ranked_codes rc\n")
        f.write("    JOIN product p ON p.code = rc.code\n")
        f.write("    ORDER BY rc.csv_pos\n")
        f.write(f"    LIMIT {target}\n")
        f.write("),\n")
        f.write("admin_user AS (\n")
        f.write(f"    SELECT user_id FROM \"user\" WHERE email = '{args.admin_email}' LIMIT 1\n")
        f.write("),\n")
        f.write("new_order AS (\n")
        f.write("    INSERT INTO \"order\" (status, total, total_no_discount, user_id,\n")
        f.write("                          contact_email, terms_and_condition, created, last_modified,\n")
        f.write("                          other_details_message)\n")
        f.write("    SELECT 'DELIVERED', 0, 0, user_id,\n")
        f.write(f"           '{args.admin_email}', TRUE, '{args.order_date}', '{args.order_date}',\n")
        f.write("           'LEGACY_SEED_BIORGANICBUBU'\n")
        f.write("    FROM admin_user\n")
        f.write("    RETURNING order_id\n")
        f.write(")\n")
        f.write("INSERT INTO order_product (order_id, product_id, product_quantity, unit_price_after_discount)\n")
        f.write("SELECT no.order_id, m.product_id,\n")
        f.write(f"       ({target} - m.rnk + 1)::int AS product_quantity,\n")
        f.write("       m.price\n")
        f.write("FROM matched m, new_order no;\n\n")

        f.write("COMMIT;\n\n")
        f.write("-- Quick check after running:\n")
        f.write("--   SELECT p.code, p.name, sum(op.product_quantity) AS sold\n")
        f.write("--   FROM order_product op JOIN product p ON p.product_id = op.product_id\n")
        f.write("--   GROUP BY p.code, p.name ORDER BY sold DESC LIMIT 20;\n")

    print(f"[seed] -> {sql_path}")
    print(f"[seed] Quantities range from {len(codes)} (top-1) down to 1 (top-{len(codes)}).")
    print(f"[seed] Apply with: docker exec -i postgres psql -U postgres -d eshop < {sql_path}")


if __name__ == "__main__":
    main()
