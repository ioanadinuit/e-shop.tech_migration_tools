"""
Migrate PrestaShop product images to Cloudflare R2 + emit product_photo SQL.

Inputs:
  --img-dir     : root of the Presta /img/p/ tree on local disk
                  (after downloading via cPanel ZIP or rsync)
  --images-csv  : CSV from sql/presta/03-images.sql
                  columns: id_image, id_product, reference, position, cover
  --out         : output directory for SQL inserts + manifest
  --r2-remote   : rclone remote name (default: r2)
  --r2-bucket   : bucket name (e.g. eshop-tech)
  --r2-prefix   : path inside bucket (default: products)
  --variant     : 'original' (id_image.jpg) or 'watermark' (id_image-watermark.jpg).
                  Default: 'watermark' — Presta-served live images usually carry the brand watermark.
  --dry-run     : print what would happen, do not call rclone or write SQL.

Outputs in --out:
  - upload-manifest.csv     : (src_path, r2_target_path) — also fed to rclone
  - product_photo.sql       : INSERT statements for product_photo table on the new platform
  - missing-images.csv      : id_images whose source file was not found on disk

Workflow:
  1. python scripts/migrate_images.py --images-csv images.csv --img-dir ./img-p \
        --r2-bucket eshop-tech --out ./img-out
  2. Inspect missing-images.csv — usually 0-5 rows, one-off DB drift.
  3. rclone copy --files-from upload-manifest.txt ./img-p r2:eshop-tech/products/
     (the manifest is already in rclone --files-from format if --rclone-files-from-out is set)
  4. Run product_photo.sql against the new platform DB.
"""
import argparse
import csv
import os
import subprocess
import sys


csv.field_size_limit(2**31 - 1)


def presta_disk_path(img_dir, id_image, variant):
    """Reconstruct the on-disk path Presta uses: /img/p/{d1}/{d2}/.../{id_image}{suffix}.jpg"""
    digits = list(str(id_image))
    suffix = "-watermark" if variant == "watermark" else ""
    return os.path.join(img_dir, *digits, f"{id_image}{suffix}.jpg")


def r2_target_path(prefix, reference, position):
    """products/{reference}/{position}.jpg — human-readable, matches DB code field."""
    safe_ref = (reference or "").strip().replace("/", "_").replace(" ", "_")
    return f"{prefix}/{safe_ref}/{position}.jpg"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--img-dir", required=True, help="Local Presta /img/p/ root")
    p.add_argument("--images-csv", required=True, help="Output of sql/presta/03-images.sql")
    p.add_argument("--out", required=True, help="Output directory for manifest + SQL")
    p.add_argument("--r2-remote", default="r2")
    p.add_argument("--r2-bucket", required=True)
    p.add_argument("--r2-prefix", default="products")
    p.add_argument("--variant", choices=["original", "watermark"], default="watermark",
                   help="Which Presta image variant to migrate. Live sites usually serve watermark.")
    p.add_argument("--public-url-base", default="",
                   help="Public URL base for product_photo.url field "
                        "(e.g. https://cdn.biotu.ro). If empty, uses r2://bucket/prefix.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--run-rclone", action="store_true",
                   help="Actually invoke rclone copy after building manifest. Otherwise prints command.")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)

    with open(args.images_csv, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"[images] {len(rows)} image rows")

    manifest, missing, photo_inserts = [], [], []
    public_base = (args.public_url_base.rstrip("/") or
                   f"r2://{args.r2_bucket}/{args.r2_prefix}")

    for r in rows:
        id_image  = (r.get("id_image") or "").strip()
        ref       = (r.get("reference") or "").strip()
        position  = (r.get("position") or "1").strip()
        cover     = (r.get("cover") or "0").strip() == "1"
        if not id_image or not ref:
            continue

        src_path  = presta_disk_path(args.img_dir, id_image, args.variant)
        r2_path   = r2_target_path(args.r2_prefix, ref, position)

        if not os.path.exists(src_path):
            missing.append({"id_image": id_image, "reference": ref, "expected_path": src_path})
            continue

        manifest.append({"src": src_path, "dst": r2_path})
        photo_inserts.append({
            "code":      ref,
            "url":       f"{public_base}/{ref}/{position}.jpg",
            "position":  position,
            "is_cover":  "1" if cover else "0",
        })

    # Manifest CSV (also useful for rclone --files-from if you reformat)
    with open(os.path.join(args.out, "upload-manifest.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["src", "dst"], quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for row in manifest:
            w.writerow(row)
    print(f"[images] {len(manifest)} files mapped -> upload-manifest.csv")

    # Missing images report
    with open(os.path.join(args.out, "missing-images.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id_image", "reference", "expected_path"],
                           quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for row in missing:
            w.writerow(row)
    print(f"[images] {len(missing)} missing on disk -> missing-images.csv")

    # SQL inserts for product_photo. Note: assumes new platform's product table has a
    # `code` column we can JOIN against. Adjust if your schema uses a different field.
    sql_path = os.path.join(args.out, "product_photo.sql")
    with open(sql_path, "w", encoding="utf-8") as f:
        f.write("-- Insert product_photo rows for migrated images.\n")
        f.write("-- Resolves product_id by JOINing on product.code.\n")
        f.write("-- Run after upload of products and after R2 transfer completes.\n\n")
        for ins in photo_inserts:
            f.write(
                f"INSERT INTO product_photo (product_id, url, position, is_cover)\n"
                f"SELECT product_id, '{ins['url']}', {ins['position']}, "
                f"{'TRUE' if ins['is_cover']=='1' else 'FALSE'} "
                f"FROM product WHERE code = '{ins['code']}';\n"
            )
    print(f"[images] {len(photo_inserts)} INSERT rows -> {sql_path}")

    # Build a flat files-list for rclone --files-from (relative to img-dir)
    files_from = os.path.join(args.out, "rclone-files-from.txt")
    with open(files_from, "w", encoding="utf-8") as f:
        for m in manifest:
            rel = os.path.relpath(m["src"], args.img_dir).replace("\\", "/")
            f.write(rel + "\n")
    print(f"[images] rclone --files-from list -> {files_from}")

    rclone_cmd = (
        f'rclone copy --files-from "{files_from}" '
        f'"{args.img_dir}" '
        f'{args.r2_remote}:{args.r2_bucket}/{args.r2_prefix}/ '
        f'--progress --transfers 32 --checkers 16'
    )
    print()
    print("=== rclone command (run manually, OR pass --run-rclone) ===")
    print(rclone_cmd)

    if args.run_rclone and not args.dry_run:
        print("\nRunning rclone…")
        subprocess.run(rclone_cmd, shell=True, check=True)


if __name__ == "__main__":
    main()
