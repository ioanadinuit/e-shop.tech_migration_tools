# e-shop.tech migration tools

Migration toolkit for moving merchants from legacy ecommerce platforms (PrestaShop, WooCommerce, Magento, custom PHP) to **e-shop.tech** — a self-hosted modular monolith ecommerce platform.

Born out of the Biotu/biorganicbubu migration (2026-05) where a single old PrestaShop instance held a tangled mix of ghost products, recycled id slots, and content scattered across language slots. The tooling here generalizes the playbook so the next merchant migration takes hours instead of days.

## Status

| Source | Categories | Producers | Products | Images | Reviews | Users | Notes |
|--------|:----------:|:---------:|:--------:|:------:|:-------:|:-----:|-------|
| **PrestaShop 1.6 / 1.7** | ✅ | ✅ | ✅ | ✅ (rclone) | ✅ | ✅ (with silent rehash) | Battle-tested on a real merchant (~6700 products, 4.5 GB images). Handles multi-shop, multi-lang, ghost slots, code/slug dedup, GDPR-aware user import. |
| WooCommerce | 🚧 | 🚧 | 🚧 | 🚧 | 🚧 | 🚧 | Adapter planned. |
| Magento 1.x / 2.x | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | Future. |

## Workflow (PrestaShop → e-shop.tech)

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Identify shop_id and lang_id of the LIVE shop                       │
│    (lang slots can be reused as inventory dumps — verify on live!)     │
├────────────────────────────────────────────────────────────────────────┤
│ 2. Run sql/presta/*.sql in phpMyAdmin → save each as CSV               │
│    - 01-categories.sql       → exports/c.csv                           │
│    - 02-products.sql         → exports/p.csv                           │
│    - 03-images.sql           → exports/i.csv                           │
│    - 04-producers.sql        → exports/producers.csv      (optional)   │
│    - 05-product-reviews.sql  → exports/reviews.csv        (optional)   │
│    - 06-customers.sql        → exports/customers.csv      (optional)   │
├────────────────────────────────────────────────────────────────────────┤
│ 3. CATALOG: python scripts/transform.py \                              │
│        --presta-dir ./exports --out ./ready                            │
│    Produces upload-ready CSVs:                                         │
│    - categorii-ready.csv                                               │
│    - legaturi-categorii-ready.csv                                      │
│    - producatori-ready.csv  (uses producers.csv if present, else from  │
│                              product names with empty descriptions)    │
│    - produse-ready.csv                                                 │
│    - produse-duplicat-de-cod.csv (manual review aside)                 │
├────────────────────────────────────────────────────────────────────────┤
│ 4. Upload via e-shop.tech admin panel CSV import flow,                 │
│    in this order: categorii → legaturi → producatori → produse         │
├────────────────────────────────────────────────────────────────────────┤
│ 5. IMAGES (after products in DB):                                      │
│    - Download Presta /img/p/ tree (cPanel ZIP or rsync)                │
│    - python scripts/migrate_images.py --img-dir ./img-p \              │
│        --images-csv ./exports/i.csv --r2-bucket your-bucket            │
│    - Generates product_photo INSERTs + rclone manifest                 │
├────────────────────────────────────────────────────────────────────────┤
│ 6. REVIEWS (optional, after products):                                 │
│    - python scripts/transform_reviews.py \                             │
│        --reviews-csv ./exports/reviews.csv --out ./ready               │
│    - Run: psql ... -f ready/product_feedback.sql                       │
├────────────────────────────────────────────────────────────────────────┤
│ 7. USERS (optional, GDPR-sensitive):                                   │
│    - python scripts/transform_users.py \                               │
│        --customers-csv ./exports/customers.csv --out ./ready \         │
│        --cookie-key "your_presta_COOKIE_KEY"                           │
│    - Run: psql ... -f ready/users.sql                                  │
│    - Add PRESTA_LEGACY_COOKIE_KEY to platform .env (for silent rehash) │
└────────────────────────────────────────────────────────────────────────┘
```

## Critical caveats (lessons learned)

Documented in detail in [docs/presta-caveats.md](docs/presta-caveats.md). Brief:

- **Lang slot reuse** — Presta `id_product` slots get recycled. lang=1 may show "current" name while lang=7 keeps OLD product name + description. Always verify which lang the live site renders before joining.
- **Multi-shop** — even single-shop installs sometimes have data in `id_shop=2` from previous tenants. Filter explicitly on shop_id everywhere.
- **Ghost vs zombie products** — `ps_product.active=1` doesn't mean live. Filter on `ps_product_shop.active=1 AND visibility != 'none'`.
- **Code reuse** — references (SKU codes) are NOT unique by default in Presta. Expect 5-20 dupes per 6000 products. Tool moves them to a `-duplicat-de-cod.csv` for manual review.
- **Slug duplication** — same product name → same slug → URL conflict. Tool auto-disambiguates with `-2`, `-3` suffix.
- **SEO data location** — meta_title/description/keywords often only populated in one specific lang (NOT necessarily the active display lang). Use the SQL queries here that join the right lang per concern.

## Setup

```bash
git clone https://github.com/ioanadinuit/e-shop.tech_migration_tools.git
cd e-shop.tech_migration_tools
pip install -r requirements.txt
```

For image migration, install [rclone](https://rclone.org/install/) and configure a remote pointing at your Cloudflare R2 bucket:

```bash
rclone config
# New remote: r2 / S3-compatible / Cloudflare provider
# Endpoint: https://{account_id}.r2.cloudflarestorage.com
```

## Output format

The tool produces CSVs matching e-shop.tech's admin upload DTOs:

- **Categories** (`categoryName, categoryUrl, disabled, discountExempt, metaTitle, metaDescription, metaKeywords`)
- **Category links** (`categoryName, subcategoryName`)
- **Producers** (`producer_name, decription, keywords, short_description`)
- **Products** (`code, name, ext_code, description, stock_count, stock_treshhold, discount, discount_percentile, discount_until, price, category_name, producer_name, meta_title, meta_description, meta_keywords, slug`)

## Contributing

Adapters for WooCommerce, Magento, OpenCart, etc. are welcome. Pattern:

1. Add `sql/<source>/` with parameterized queries (or `extractors/<source>.py` for direct DB connection).
2. Add `scripts/transform_<source>.py` reading source CSVs and emitting the platform's upload format.
3. Document caveats in `docs/<source>-caveats.md`.

## License

MIT.
