-- Manufacturers (producers) with description + SEO from a chosen lang slot.
-- Parameters:
--   :SHOP_ID  → e.g. 1
--   :LANG_ID  → e.g. 7  (lang where description/SEO was actually filled in;
--                          most merchants leave manufacturer_lang empty entirely)
--
-- Output: id_manufacturer, name, description, short_description,
--         meta_title, meta_description, meta_keywords, active

SELECT m.id_manufacturer,
       m.name,
       ml.description,
       ml.short_description,
       ml.meta_title,
       ml.meta_description,
       ml.meta_keywords,
       m.active
FROM ps_manufacturer m
JOIN ps_manufacturer_shop ms ON ms.id_manufacturer = m.id_manufacturer
                              AND ms.id_shop = :SHOP_ID
LEFT JOIN ps_manufacturer_lang ml ON ml.id_manufacturer = m.id_manufacturer
                                  AND ml.id_lang = :LANG_ID
WHERE m.active = 1
ORDER BY m.id_manufacturer;
