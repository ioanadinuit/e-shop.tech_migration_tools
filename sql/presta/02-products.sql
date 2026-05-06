-- Products with full content (description, SEO, slug) + default category + producer name.
-- Parameters: :SHOP_ID, :LANG_ID  (same caveat as 01-categories.sql)
--
-- Filters applied (anti-zombie):
--   - product is active in shop
--   - visibility != 'none'
--   - has a price > 0
--   - has a name in the chosen lang
--
-- Output columns map directly into the e-shop.tech ProductUploadCsvDTO via transform.py.

SELECT p.id_product,
       p.reference,
       ps.price,
       ps.active,
       ps.visibility,
       pl.id_lang,
       pl.name,
       pl.description,
       pl.description_short,
       pl.link_rewrite,
       pl.meta_description,
       pl.meta_keywords,
       pl.meta_title,
       cl.name AS category_name,
       m.name  AS manufacturer_name
FROM ps_product p
JOIN ps_product_shop ps ON ps.id_product = p.id_product
                         AND ps.id_shop  = :SHOP_ID
JOIN ps_product_lang pl ON pl.id_product = p.id_product
                         AND pl.id_shop  = :SHOP_ID
                         AND pl.id_lang  = :LANG_ID
LEFT JOIN ps_category_lang cl ON cl.id_category = ps.id_category_default
                              AND cl.id_lang   = :LANG_ID
                              AND cl.id_shop   = :SHOP_ID
LEFT JOIN ps_manufacturer m ON m.id_manufacturer = p.id_manufacturer
WHERE ps.active = 1
  AND ps.visibility != 'none'
  AND p.price > 0
  AND pl.name IS NOT NULL
ORDER BY p.id_product;
