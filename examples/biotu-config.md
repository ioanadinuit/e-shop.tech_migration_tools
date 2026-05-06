# Example — Biotu / biorganicbubu migration (2026-05)

Real config used for the maiden voyage. Anonymize before sharing.

## Source

- Platform: PrestaShop 1.6
- Domain: biorganicbubu.ro
- Single shop (`id_shop=1`, name "Biorganicbaby")
- Multi-lang DB but only **lang_id=7** has live content + descriptions
- ~6700 active products + 435 categories + 214 manufacturers

## Commands run

```bash
# 1. Run SQL queries (with :SHOP_ID=1, :LANG_ID=7) in phpMyAdmin, save as:
#    exports/c.csv  (categories)
#    exports/p.csv  (products)
#    exports/i.csv  (images)

# 2. Transform to upload-ready CSVs
python scripts/transform.py --presta-dir ./exports --out ./ready

# 3. Upload via e-shop.tech admin in this order:
#    - ready/categorii-ready.csv
#    - ready/legaturi-categorii-ready.csv
#    - ready/producatori-ready.csv
#    - ready/produse-ready.csv

# 4. Image migration (after products are in DB)
python scripts/migrate_images.py \
    --img-dir ./img-p \
    --images-csv ./exports/i.csv \
    --out ./img-out \
    --r2-bucket eshop-tech \
    --variant watermark \
    --public-url-base https://cdn.biotu.ro

# Then:
rclone copy --files-from img-out/rclone-files-from.txt \
    ./img-p r2:eshop-tech/products/ \
    --progress --transfers 32

# Finally, run the SQL inserts on the new platform DB:
psql ... -f img-out/product_photo.sql
```

## Outcome

- 435 categories with full SEO populated
- 6734 products with rich HTML descriptions + meta_*
- 10 products held aside for manual triage (`-duplicat-de-cod.csv`)
- ~7700 images migrated to R2

## Quirks discovered

See `docs/presta-caveats.md` for the full list. Highlights for this merchant:

- 5 reused SKU references (e.g., BH177 used for both a cosmetic and a detergent — same id_product slot, different lang)
- `lang_id=1` was a half-finished rebrand attempt — names changed but descriptions never written. Initial migration accidentally used this slot, had to redo from `lang_id=7`.
- ~1500 products without slugs in lang=1 → caught only by re-running with lang=7.
