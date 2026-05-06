"""
Transform PrestaShop CSV exports into e-shop.tech upload-ready CSVs.

Inputs (CSVs produced by running sql/presta/*.sql in phpMyAdmin):
  --presta-dir/c.csv  (categories from 01-categories.sql)
  --presta-dir/p.csv  (products from 02-products.sql)

Outputs (in --out):
  - categorii-ready.csv               (category metadata + SEO)
  - legaturi-categorii-ready.csv      (parent -> child relations, derived locally
                                        via self-join on id_parent)
  - producatori-ready.csv             (deduped from products' manufacturer_name column)
  - produse-ready.csv                 (products with unique codes, slug-deduplicated)
  - produse-duplicat-de-cod.csv       (rows where ps_product.reference is reused for
                                        multiple distinct products — manual review)

Usage:
  python scripts/transform.py --presta-dir ./exports --out ./ready

Run:
  python scripts/transform.py --help
"""
import argparse
import csv
import os
import sys
from collections import Counter, OrderedDict


# CSV cell limits — Presta descriptions can be 5000+ HTML chars per row.
csv.field_size_limit(2**31 - 1)


CATEGORY_OUT_COLS = [
    "categoryName", "categoryUrl", "disabled", "discountExempt",
    "metaTitle", "metaDescription", "metaKeywords",
]
LINK_OUT_COLS = ["categoryName", "subcategoryName"]
PRODUCER_OUT_COLS = ["producer_name", "decription", "keywords", "short_description"]
PRODUCT_OUT_COLS = [
    "code", "name", "ext_code", "description",
    "stock_count", "stock_treshhold",
    "discount", "discount_percentile", "discount_until", "price",
    "category_name", "producer_name",
    "meta_title", "meta_description", "meta_keywords", "slug",
]


def _read_dict_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_dict_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ── Category transform ──────────────────────────────────────────────────────

def transform_categories(presta_categories_csv, out_dir):
    rows = _read_dict_csv(presta_categories_csv)
    print(f"[categories] {len(rows)} rows read")

    # Categories ready
    categories = []
    for r in rows:
        categories.append({
            "categoryName":    (r.get("name") or "").strip(),
            "categoryUrl":     (r.get("uri") or r.get("link_rewrite") or "").strip(),
            "disabled":        "false",
            "discountExempt":  "false",
            "metaTitle":       (r.get("meta_title") or "").strip(),
            "metaDescription": (r.get("meta_description") or "").strip(),
            "metaKeywords":    (r.get("meta_keywords") or "").strip(),
        })
    _write_dict_csv(os.path.join(out_dir, "categorii-ready.csv"), CATEGORY_OUT_COLS, categories)
    print(f"[categories] -> categorii-ready.csv ({len(categories)} rows)")

    # Self-join parent -> child for links
    id_to_name = {r["id_category"]: (r.get("name") or "").strip() for r in rows}
    links, orphans = [], 0
    for r in rows:
        parent_id = (r.get("id_parent") or "").strip()
        parent_name = id_to_name.get(parent_id)
        child_name = (r.get("name") or "").strip()
        if not parent_name:
            orphans += 1
            continue
        if not child_name:
            continue
        links.append({"categoryName": parent_name, "subcategoryName": child_name})
    _write_dict_csv(os.path.join(out_dir, "legaturi-categorii-ready.csv"), LINK_OUT_COLS, links)
    print(f"[categories] -> legaturi-categorii-ready.csv ({len(links)} links, {orphans} root-level skipped)")


# ── Producer + Product transform ────────────────────────────────────────────

def transform_producers(presta_producers_csv, fallback_product_rows, out_dir):
    """Prefer the dedicated 04-producers.sql export (with description/SEO fields).
    Fall back to extracting unique manufacturer_name from product rows if not provided."""
    if presta_producers_csv and os.path.exists(presta_producers_csv):
        rows = _read_dict_csv(presta_producers_csv)
        producers = []
        for r in rows:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            producers.append({
                "producer_name":     name,
                "decription":        (r.get("description") or "").strip(),
                "keywords":          (r.get("meta_keywords") or "").strip(),
                "short_description": (r.get("short_description") or "").strip(),
            })
        _write_dict_csv(os.path.join(out_dir, "producatori-ready.csv"), PRODUCER_OUT_COLS, producers)
        print(f"[producers] -> producatori-ready.csv ({len(producers)} from dedicated export)")
    else:
        # Fallback: just unique names from products
        seen = OrderedDict()
        for r in fallback_product_rows:
            name = (r.get("manufacturer_name") or "").strip()
            if name and name not in seen:
                seen[name] = {
                    "producer_name":     name,
                    "decription":        "",
                    "keywords":          "",
                    "short_description": "",
                }
        _write_dict_csv(os.path.join(out_dir, "producatori-ready.csv"), PRODUCER_OUT_COLS,
                        list(seen.values()))
        print(f"[producers] -> producatori-ready.csv ({len(seen)} unique names extracted from products; "
              f"no dedicated CSV — descriptions empty)")


def transform_products(presta_products_csv, out_dir):
    rows = _read_dict_csv(presta_products_csv)
    print(f"[products] {len(rows)} rows read")

    # ── Products: split duplicate codes vs main, dedup slugs in main ─────────
    code_counts = Counter((r.get("reference") or "").strip()
                          for r in rows if (r.get("reference") or "").strip())
    duplicate_codes = {c for c, n in code_counts.items() if n > 1}
    print(f"[products] {len(duplicate_codes)} reference codes appear >1 time "
          f"-> moved aside: {sorted(duplicate_codes)}")

    seen_slugs, slug_dedup = {}, 0
    main_rows, dup_rows = [], []
    for r in rows:
        code = (r.get("reference") or "").strip()
        if not code:
            continue  # skip rows with no SKU code

        out = {
            "code":                code,
            "name":                (r.get("name") or "").strip(),
            "ext_code":            "",
            "description":         (r.get("description") or "").strip(),
            "stock_count":         "",
            "stock_treshhold":     "",
            "discount":            "",
            "discount_percentile": "",
            "discount_until":      "",
            "price":               (r.get("price") or "").strip(),
            "category_name":       (r.get("category_name") or "").strip(),
            "producer_name":       (r.get("manufacturer_name") or "").strip(),
            "meta_title":          (r.get("meta_title") or "").strip(),
            "meta_description":    (r.get("meta_description") or "").strip(),
            "meta_keywords":       (r.get("meta_keywords") or "").strip(),
            "slug":                (r.get("link_rewrite") or "").strip(),
        }

        if code in duplicate_codes:
            dup_rows.append(out)
            continue

        if out["slug"]:
            n = seen_slugs.get(out["slug"], 0) + 1
            seen_slugs[out["slug"]] = n
            if n > 1:
                out["slug"] = f"{out['slug']}-{n}"
                slug_dedup += 1

        main_rows.append(out)

    _write_dict_csv(os.path.join(out_dir, "produse-ready.csv"), PRODUCT_OUT_COLS, main_rows)
    print(f"[products] -> produse-ready.csv ({len(main_rows)} rows, {slug_dedup} slugs disambiguated)")

    _write_dict_csv(os.path.join(out_dir, "produse-duplicat-de-cod.csv"), PRODUCT_OUT_COLS, dup_rows)
    print(f"[products] -> produse-duplicat-de-cod.csv ({len(dup_rows)} rows for manual review)")


# ── CLI entry point ─────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--presta-dir", required=True,
                   help="Directory containing c.csv (categories) and p.csv (products) "
                        "from sql/presta/*.sql")
    p.add_argument("--out", required=True,
                   help="Output directory for the upload-ready CSVs")
    p.add_argument("--categories-file", default="c.csv",
                   help="Filename of categories export (default: c.csv)")
    p.add_argument("--products-file", default="p.csv",
                   help="Filename of products export (default: p.csv)")
    p.add_argument("--producers-file", default="producers.csv",
                   help="Optional: dedicated producers export from 04-producers.sql "
                        "(default: producers.csv). If missing, producer names are extracted "
                        "from products with empty descriptions.")
    args = p.parse_args()

    cat_path = os.path.join(args.presta_dir, args.categories_file)
    prod_path = os.path.join(args.presta_dir, args.products_file)
    producers_path = os.path.join(args.presta_dir, args.producers_file)

    if not os.path.exists(cat_path):
        sys.exit(f"ERROR: categories CSV not found: {cat_path}")
    if not os.path.exists(prod_path):
        sys.exit(f"ERROR: products CSV not found: {prod_path}")

    os.makedirs(args.out, exist_ok=True)
    transform_categories(cat_path, args.out)
    # Read products once; pass to producers as fallback source if the dedicated CSV is missing.
    product_rows = _read_dict_csv(prod_path)
    transform_producers(producers_path, product_rows, args.out)
    transform_products(prod_path, args.out)
    print(f"\nDone. Files in: {args.out}")


if __name__ == "__main__":
    main()
