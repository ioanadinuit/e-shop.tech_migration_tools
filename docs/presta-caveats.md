# PrestaShop migration — caveats & lessons learned

Real-world quirks that bit during the Biotu/biorganicbubu migration (Presta 1.6, 2026-05). Treat these as hypotheses to verify before trusting any export.

## 1. Lang slot reuse — the killer

PrestaShop has multiple "language" slots in `ps_product_lang` and `ps_category_lang`. They are typically translations, **but in long-lived merchants the slots get repurposed**:
- One slot holds the live shop's content
- Another slot holds an old / draft / abandoned rebrand attempt
- A third slot holds data from a sister shop that ran on the same DB

**Symptom:** the same `id_product` has totally different names in different `id_lang` slots, sometimes even different physical products. Example: `id_product=4641` had `name="Fard de pleoape"` in lang=1 and `name="Detergent lichid"` in lang=7 with rich description.

**Diagnostic:**
1. Open a product page on the LIVE shop. Note the displayed name + check if there's a description.
2. `SELECT id_lang, name, description FROM ps_product_lang WHERE id_product = X` — find which lang matches the live page. THAT is the live lang.
3. The other slots are noise. Do NOT join across them by ID.

**Lesson for tooling:** make `lang_id` an explicit parameter in every SQL. Never default to 1.

## 2. Multi-shop with single shop

`ps_shop` table tells you how many shops exist. Even if there's only one, content might still be stored under `id_shop=1` in some tables and `id_shop=0` (default fallback) in others. **Always filter on shop_id explicitly.**

## 3. "Active" doesn't mean "live"

Three independent flags determine whether a product shows on live:
- `ps_product.active = 1`
- `ps_product_shop.active = 1`
- `ps_product_shop.visibility != 'none'`

Filter on all three. Otherwise you get zombie rows that the merchant deleted from front-of-house but kept in the DB.

## 4. SKU code (ps_product.reference) is NOT unique

PrestaShop treats `reference` as a free-form string field with no uniqueness constraint. Merchants reuse it intentionally (one per category) or by typo accident.

**Common pattern: "discount-clone hack."** Some merchants duplicate a product, apply a discount on the clone, sell off the cloned one, then forget to delete it. Result: 5-15 stale duplicate-reference rows hanging out in the DB years later. Almost always safe to drop them — verify with the merchant per-pair (real Biotu case: all 10 dupes / 5 pairs were exactly this, dropped without issue).

**Tool behavior:** `transform.py` moves all rows whose `reference` appears more than once into a `produse-duplicat-de-cod.csv` for manual triage. Default behavior is to flag, not drop — the merchant decides per case.

## 5. Slug duplication is normal

Same product name → same `link_rewrite` (slug) → URL conflict on the new platform. Common scenario: merchant lists 3 SKUs of the same physical product with same name but different reference codes — they all share the same slug.

**Tool behavior:** `transform.py` auto-suffixes second/third/Nth occurrence with `-2`, `-3`, etc. Slugs become URL-safe but ugly. Post-migration, the merchant can rewrite slugs through the platform admin to taste.

## 6. SEO data lives in the lang you wouldn't expect

Even when lang=1 is the active display lang, `meta_title / meta_description / meta_keywords` are sometimes only populated in another slot (e.g., lang=7) because at some point someone did SEO work in a different lang and never copied it over. **Verify SEO population per lang before picking your join lang:**

```sql
SELECT id_lang,
       COUNT(*) total,
       SUM(IF(meta_title IS NOT NULL AND meta_title != '', 1, 0)) with_meta
FROM ps_product_lang GROUP BY id_lang;
```

## 7. Image storage layout

`/img/p/{d1}/{d2}/{d3}/.../{id_image}.jpg` where digits are taken from `id_image` itself (e.g., id_image=46408 → /4/6/4/0/8/46408.jpg). Plus 12+ pre-resized variants per image.

Pre-resized variants: `*-cart_default.jpg`, `*-home_default.jpg`, `*-large_default.jpg`, `*-medium_default.jpg`, `*-small_default.jpg`, `*-thickbox_default.jpg` and theme-specific `*-tm_*` variants. **Modern platforms resize on-demand** — only migrate the originals.

Watermark vs clean: Presta themes can serve `*-watermark.jpg` to show a brand stamp. Check what the live site renders before deciding which to migrate.

## 8. Image-to-product mapping is in `ps_image_shop`, not `ps_image`

`ps_image` lists all images that ever existed. `ps_image_shop` says which are visible per shop, plus their position (gallery order) and cover flag. **Always join through `ps_image_shop`** to avoid migrating orphan images that aren't in any shop.

## 9. Manufacturer descriptions usually don't exist in exports

Stock Presta exports `ps_manufacturer` (id, name, active) and `ps_manufacturer_lang` (description, meta) — but most merchants leave the lang fields empty. If you need producer descriptions, you'll likely have to scrape them or AI-generate.

## 10. Categories root vs Home

Every Presta install has `id_category=1` (Root) and `id_category=2` (Home). Filter them out — they're navigation pseudo-categories, not real catalog nodes.

```sql
WHERE c.id_parent != 0
  AND cl.name NOT IN ('Home', 'Root')
```

## 11. Single-image products vs gallery

Most products have 1-3 images (cover + 1-2 angles). Some have 10+. Migrate ALL via `ps_image_shop.position` ordering — never cherry-pick to "save time" because customers reaching detail pages of products with missing secondary images get a worse experience than a fully-migrated catalog.

## 12. Manufacturer descriptions: schema present, data rare

`ps_manufacturer_lang` has columns for description, short_description, meta_title, meta_description, meta_keywords. **In practice, most merchants leave these empty** — they fill out manufacturer NAME (which is required) and skip the rest. `04-producers.sql` extracts whatever's there; `transform.py` falls back to extracting just unique names from product rows when the dedicated CSV has no usable content.

If you need rich producer pages on the new platform: AI-generate from name alone, or scrape from each manufacturer's website.

## 13. Product reviews — only validated ones

`ps_product_comment.validate = 1` means an admin approved the comment. Anything else is pending moderation, spam, or rejected. **Never migrate non-validated reviews** — you'd inherit the merchant's spam pile from years past.

Also: `ps_product_comment.deleted` is a soft-delete flag. Filter `deleted = 0`.

Multi-criterion grading (taste, quality, value-for-money) is supported by `ps_product_comment_grade`, joined to `ps_product_comment_criterion`. The `05-product-reviews.sql` query AVG()-s these into a single rating — adequate when most merchants only used one default criterion. If the merchant used multiple criteria meaningfully, consider preserving them as separate columns or migrating only the average.

## 14. Customer migration — silent rehash, no forced reset

PrestaShop ≤ 1.7.4 hashes passwords with **MD5 + a per-shop static salt** (`_COOKIE_KEY_` from `config/settings.inc.php`). Newer Presta uses bcrypt/argon. Either way, forcing every customer to reset their password on day 1 of the new platform is a UX disaster — you'd lose 30-60% of accounts to "I'll do it later" attrition.

The platform's `AuthenticationService` supports a silent-rehash flow: at login, if the user has a `legacy_password_hash` of type `PRESTA_MD5`, verify with the cookie key, accept the login, and immediately rehash to bcrypt + clear the legacy fields. User experience: they log in with the same password they always used. Subsequent logins use bcrypt.

For this to work the migration tool must:
1. Preserve `legacy_password_hash` (the raw `ps_customer.passwd` value) on import
2. Mark `legacy_password_type = 'PRESTA_MD5'`
3. Set `password` to a placeholder bcrypt that no plaintext can match
4. Provide the `_COOKIE_KEY_` to the platform via env var (`PRESTA_LEGACY_COOKIE_KEY`)

`scripts/transform_users.py` does (1)-(3) automatically; the merchant ops team handles (4) — and treats the cookie key as a secret.

## 15. GDPR posture for user migration

The agency running the migration is the **processor** (handling personal data on behalf of someone else). The merchant remains the **controller** (decides why and how). A signed Article 28 Data Processing Agreement should exist before touching the customer table.

Customer data should:
- Live only on the agency engineer's local machine + the production target. Never the public internet, never shared cloud drives without DPA.
- Be deleted from the local machine within ~30 days of migration go-live, after the silent-rehash flow is verified working in production.
- Be excluded from any source repo (`exports/customers.csv` is in the `.gitignore` here for that reason).

Newsletter consent (`ps_customer.newsletter`) should be migrated as-is — re-opt-in is technically required only for new bases under post-2018 GDPR interpretation, but for an existing customer base where the merchant already collected consent, importing the flag is acceptable. Document the legal basis in your migration runbook.

---

If you hit something weird not in this list, document it back here. Each merchant adds 1-2 new gotchas to discover.
