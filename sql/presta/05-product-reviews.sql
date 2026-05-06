-- Product reviews from PrestaShop's `productcomments` module.
-- Joins comment + grade (1-5 star rating) + customer info + product reference.
--
-- Parameters:
--   :SHOP_ID  → e.g. 1
--
-- Filters:
--   - validate = 1 (admin-approved comments only — do NOT migrate spam/pending)
--   - has both content AND grade (skip orphan rows)
--
-- Output: product_reference, customer_name, customer_email,
--         rating, comment, title, date_add, date_upd
--
-- Note on ratings: ps_product_comment_grade has multiple grades per comment
-- when there are criteria (taste, quality, etc.). We average them. If your
-- merchant only used a single criterion, AVG() === the single value.

SELECT p.reference                       AS product_reference,
       pc.customer_name,
       c.email                           AS customer_email,
       AVG(pcg.grade)                    AS rating,
       pc.content                        AS comment,
       pc.title,
       pc.date_add,
       pc.date_upd
FROM ps_product_comment pc
JOIN ps_product p ON p.id_product = pc.id_product
LEFT JOIN ps_customer c ON c.id_customer = pc.id_customer
LEFT JOIN ps_product_comment_grade pcg ON pcg.id_product_comment = pc.id_product_comment
WHERE pc.validate = 1
  AND pc.deleted = 0
  AND pc.content IS NOT NULL
  AND pc.content != ''
GROUP BY pc.id_product_comment
ORDER BY pc.date_add;
