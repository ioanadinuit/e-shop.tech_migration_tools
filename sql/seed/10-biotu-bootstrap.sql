-- Biotu launch bootstrap data: shop_details + invoicing + shipping_config.
-- Idempotent: each block guards with NOT EXISTS so re-running is safe even
-- after manual edits in the admin UI (we never overwrite tweaked rows).
-- Replace REG_COM / CUI / IBAN / phones with real values before production.

BEGIN;

-- ── shop_details ────────────────────────────────────────────────────────────
INSERT INTO shop_details (
    country, county, address, postal_code, shop_name, working_hours, contact_hours,
    phone, contact_email, shop_url, currency_alpha_code,
    uses_stock_management, return_days, min_order_total,
    free_shipping_threshold, default_shipping_cost,
    guest_checkout_enabled, last_seen_count, payment_link_expiry_hours,
    incident_email, free_shipping_max_weight_grams, max_order_weight_grams,
    overweight_surcharge_per_kg, fuzzy_match_threshold
)
SELECT
    'Romania', 'Bucuresti',
    'Strada Exemplu nr. 1, sector 3', '030001',
    'Biotu', 'Luni-Vineri 09:00-17:00', 'Luni-Vineri 09:00-17:00',
    '+40 700 000 000', 'contact@biotu.ro', 'https://biotu.ro', 'RON',
    FALSE,                  -- uses_stock_management (per release_stock_disabled_mode memo)
    14,                     -- return_days
    50.00,                  -- min_order_total
    250.00,                 -- free_shipping_threshold
    19.99,                  -- default_shipping_cost
    TRUE,                   -- guest_checkout_enabled
    5,                      -- last_seen_count
    48,                     -- payment_link_expiry_hours
    'incidents@biotu.ro',
    20000,                  -- free_shipping_max_weight_grams (20 kg)
    30000,                  -- max_order_weight_grams (30 kg)
    5.00,                   -- overweight_surcharge_per_kg
    80.00                   -- fuzzy_match_threshold
WHERE NOT EXISTS (SELECT 1 FROM shop_details);

-- ── shop_details_invoicing ──────────────────────────────────────────────────
-- Single row tied to the only shop_details row above.
-- Note: per client_non_vat_payer memo, DANUCOL SRL e neplatitor TVA — so no
-- VAT logic on the invoice template; just clean line items.
INSERT INTO shop_details_invoicing (
    shop_id, company_name, cui, reg_com,
    country, county, city, address, postal_code,
    bank_name, account_holder, iban, swift,
    phone, email, invoice_prefix, due_days
)
SELECT
    s.shop_id, 'DANUCOL SRL', 'RO00000000', 'J40/0000/2024',
    'Romania', 'Bucuresti', 'Bucuresti',
    'Strada Exemplu nr. 1, sector 3', '030001',
    'Banca Transilvania', 'DANUCOL SRL', 'RO00BTRL0000000000000000', 'BTRLRO22',
    '+40 700 000 000', 'facturi@biotu.ro', 'BIO', 0
FROM shop_details s
WHERE NOT EXISTS (SELECT 1 FROM shop_details_invoicing);

-- ── shipping_config ─────────────────────────────────────────────────────────
-- Mirrors the legacy fields on shop_details (defaults match what the
-- shipping calculator falls back to). Admin can fine-tune per zone later
-- via shipping_zone / shipping_zone_county / shipping_zone_weight_tier.
INSERT INTO shipping_config (
    shop_id, default_shipping_cost, free_shipping_threshold,
    free_shipping_max_weight_grams, max_order_weight_grams,
    overweight_surcharge_per_kg
)
SELECT
    s.shop_id, 19.99, 250.00, 20000, 30000, 5.00
FROM shop_details s
WHERE NOT EXISTS (SELECT 1 FROM shipping_config);

COMMIT;

-- Sanity check after running:
--   SELECT shop_name, contact_email, currency_alpha_code FROM shop_details;
--   SELECT company_name, cui, iban FROM shop_details_invoicing;
--   SELECT default_shipping_cost, free_shipping_threshold FROM shipping_config;
