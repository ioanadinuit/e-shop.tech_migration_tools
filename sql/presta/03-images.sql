-- Full image gallery per product (cover + secondary), ordered by position.
-- Parameters: :SHOP_ID
--
-- Output: id_image, id_product, reference, position, cover
--
-- migrate_images.py uses this to map id_image -> on-disk path
--   ( /img/p/{digit1}/{digit2}/.../{id_image}.jpg )
-- and target R2 path:
--   products/{reference}/{position}.jpg

SELECT i.id_image,
       i.id_product,
       p.reference,
       isr.position,
       isr.cover
FROM ps_image i
JOIN ps_image_shop isr ON isr.id_image = i.id_image
                        AND isr.id_shop = :SHOP_ID
JOIN ps_product p ON p.id_product = i.id_product
ORDER BY i.id_product, isr.position;
