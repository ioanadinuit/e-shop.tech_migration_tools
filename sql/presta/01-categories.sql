-- Categories with SEO from a chosen lang slot.
-- Parameters to substitute before running:
--   :SHOP_ID  → e.g. 1  (the live shop)
--   :LANG_ID  → e.g. 7  (the lang slot whose names + SEO are shown on live site;
--                          NOT necessarily lang=1 — see docs/presta-caveats.md)
--
-- Output: id_category, id_parent, name, uri, meta_title, meta_description, meta_keywords
-- Excludes Root + Home pseudo-categories and any inactive ones.

SELECT c.id_category,
       c.id_parent,
       cl.name,
       cl.link_rewrite AS uri,
       cl.meta_title,
       cl.meta_description,
       cl.meta_keywords
FROM ps_category c
JOIN ps_category_shop cs ON cs.id_category = c.id_category
                          AND cs.id_shop  = :SHOP_ID
JOIN ps_category_lang cl ON cl.id_category = c.id_category
                          AND cl.id_shop  = :SHOP_ID
                          AND cl.id_lang  = :LANG_ID
WHERE c.active = 1
  AND c.id_parent != 0
  AND cl.name NOT IN ('Home', 'Root')
ORDER BY c.id_category;
