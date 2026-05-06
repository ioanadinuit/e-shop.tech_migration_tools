-- Customers + their primary delivery address.
-- Parameters:
--   :SHOP_ID  → e.g. 1
--
-- Filters:
--   - active = 1 (deleted/banned customers excluded)
--   - has email (skip orphan rows)
--
-- Output columns suitable for transform_users.py.
--
-- ⚠ GDPR: this CSV will contain personal data (names, emails, phones, addresses).
-- Treat as confidential. Article 28 DPA between agency and merchant should be
-- in place before extraction. Do NOT commit this CSV to any repo.
--
-- Password handling: ps_customer.passwd holds the legacy MD5 hash with the
-- shop's _COOKIE_KEY_ salt (Presta < 1.7.4) or bcrypt/argon (newer).
-- Old MD5 hashes can be silently rehashed on first login — see the platform's
-- AuthenticationService.authenticate flow + legacy_password_hash columns on
-- the user table. Provide --cookie-key when running transform_users.py.

SELECT c.id_customer,
       c.firstname,
       c.lastname,
       c.email,
       c.passwd                          AS legacy_password_hash,
       c.birthday,
       c.newsletter,
       c.optin,
       c.active,
       c.date_add                        AS created_at,
       c.date_upd                        AS updated_at,
       a.address1                        AS street,
       a.postcode                        AS postal_code,
       a.city,
       a.phone,
       a.phone_mobile,
       co.iso_code                       AS country_code,
       co.name                           AS country_name
FROM ps_customer c
LEFT JOIN ps_address a ON a.id_customer = c.id_customer
                       AND a.deleted = 0
                       AND a.active = 1
LEFT JOIN ps_country co ON co.id_country = a.id_country
WHERE c.active = 1
  AND c.email IS NOT NULL
  AND c.email != ''
GROUP BY c.id_customer    -- keep one address per customer (the latest non-deleted)
ORDER BY c.id_customer;
