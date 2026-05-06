"""
Transform PrestaShop customers into SQL INSERTs for e-shop.tech user tables.

Input: CSV from sql/presta/06-customers.sql.

Output:
  users.sql  — INSERTs into "user" + authentication + role + user_address.
               The authentication.password column is set to a placeholder that
               cannot match any real bcrypt hash, while authentication.legacy_password_hash
               + legacy_password_type carry the original Presta MD5 hash.
               On first login, the platform's AuthenticationService should
               recognize the legacy type, verify with cookie_key, and silently
               rehash to bcrypt — no forced password reset for migrated users.

⚠ GDPR: this script handles personally identifiable information. The agency
running the migration is the processor; the merchant is the controller. An
Article 28 DPA must be in place before running. Do NOT commit the input CSV.

Usage:
  python scripts/transform_users.py \\
      --customers-csv ./exports/customers.csv \\
      --out ./ready \\
      --cookie-key "abc123def456..."

  --cookie-key is the merchant's Presta `_COOKIE_KEY_` (find in
  config/settings.inc.php on Presta 1.6 or app/config/parameters.php on 1.7+).
  It's NOT used by this script directly — it's stored in a small `.env.fragment`
  file in --out so the platform's auth service can verify legacy hashes.
"""
import argparse
import csv
import os
import sys
import uuid


csv.field_size_limit(2**31 - 1)


def _sql_escape(s):
    if s is None or s == "":
        return "NULL"
    s = str(s).replace("'", "''")
    return f"'{s}'"


def _bool_sql(s):
    """Presta stores booleans as '0'/'1'. Convert to SQL boolean literal."""
    return "TRUE" if str(s).strip() == "1" else "FALSE"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--customers-csv", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cookie-key", required=False, default="",
                   help="Presta _COOKIE_KEY_ — printed to .env.fragment for the platform's auth service")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)

    with open(args.customers_csv, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"[users] {len(rows)} customer rows read")

    # Dedup by email (Presta sometimes has the same email under multiple customer ids)
    by_email = {}
    for r in rows:
        email = (r.get("email") or "").strip().lower()
        if not email:
            continue
        # Keep the latest by updated_at (lexical compare on ISO timestamps is fine)
        if email not in by_email or (r.get("updated_at") or "") > (by_email[email].get("updated_at") or ""):
            by_email[email] = r
    print(f"[users] {len(by_email)} unique emails (after dedup)")

    sql_path = os.path.join(args.out, "users.sql")
    skipped_no_pass = 0

    with open(sql_path, "w", encoding="utf-8") as f:
        f.write("-- Migrated PrestaShop customers.\n")
        f.write("-- Idempotent: safe to re-run, INSERTs guarded by ON CONFLICT (email) DO NOTHING.\n")
        f.write("-- Authentication uses the platform's silent-rehash flow — see\n")
        f.write("-- AuthenticationService for how legacy_password_hash is consumed at login.\n\n")
        f.write("BEGIN;\n\n")

        for email, r in by_email.items():
            legacy_hash = (r.get("legacy_password_hash") or "").strip()
            if not legacy_hash:
                skipped_no_pass += 1
                continue

            first = (r.get("firstname") or "").strip()
            last = (r.get("lastname") or "").strip()
            birthdate = (r.get("birthday") or "").strip()
            if birthdate in ("0000-00-00", ""):
                birthdate = None
            newsletter = _bool_sql(r.get("newsletter", "0"))
            created_at = (r.get("created_at") or "").strip()
            cust_ref = str(uuid.uuid4())

            # 1. Insert user
            f.write(
                'INSERT INTO "user" (first_name, last_name, email, newsletter, active_account, '
                'birthdate, gdpr, terms_and_condition, gdpr_accept_timestamp, terms_accept_timestamp, '
                'account_confirmed, banned, guest, cust_ref, created_at)\n'
                f"VALUES ({_sql_escape(first)}, {_sql_escape(last)}, {_sql_escape(email)}, "
                f"{newsletter}, TRUE, {_sql_escape(birthdate)}, TRUE, TRUE, "
                f"{_sql_escape(created_at)}, {_sql_escape(created_at)}, "
                f"TRUE, FALSE, FALSE, {_sql_escape(cust_ref)}, {_sql_escape(created_at)})\n"
                "ON CONFLICT (email) DO NOTHING;\n"
            )

            # 2. Insert authentication with legacy hash (placeholder bcrypt that nobody can match)
            placeholder_pw = f"MIGRATED_{cust_ref}"
            f.write(
                'INSERT INTO authentication (user_id, username, last_pass_setup, password, '
                'legacy_password_hash, legacy_password_type)\n'
                f"SELECT user_id, {_sql_escape(email)}, {_sql_escape(created_at)}, "
                f"{_sql_escape(placeholder_pw)}, {_sql_escape(legacy_hash)}, 'PRESTA_MD5'\n"
                f'FROM "user" WHERE email = {_sql_escape(email)}\n'
                "ON CONFLICT (user_id) DO NOTHING;\n"
            )

            # 3. Role = USER
            f.write(
                "INSERT INTO role (user_id, role)\n"
                f"SELECT user_id, 'USER'::role_type FROM \"user\" WHERE email = {_sql_escape(email)}\n"
                "ON CONFLICT (user_id) DO NOTHING;\n"
            )

            # 4. Address (if available)
            street = (r.get("street") or "").strip()
            postal = (r.get("postal_code") or "").strip()
            city = (r.get("city") or "").strip()
            phone = (r.get("phone") or r.get("phone_mobile") or "").strip()
            country = (r.get("country_name") or "Romania").strip()
            if street or city:
                f.write(
                    'INSERT INTO user_address (user_id, country, county, city, street, '
                    'postal_code, phone, "primary", updated_at)\n'
                    f"SELECT user_id, {_sql_escape(country)}, NULL, {_sql_escape(city)}, "
                    f"{_sql_escape(street)}, {_sql_escape(postal)}, {_sql_escape(phone)}, "
                    f"TRUE, {_sql_escape(created_at)}\n"
                    f'FROM "user" WHERE email = {_sql_escape(email)};\n'
                )

            f.write("\n")

        f.write("COMMIT;\n")

    print(f"[users] -> users.sql ({len(by_email) - skipped_no_pass} customers, "
          f"{skipped_no_pass} skipped for missing password hash)")

    # Save cookie key as a separate fragment for ops to load into the new platform's .env
    if args.cookie_key:
        env_path = os.path.join(args.out, ".env.fragment")
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f'PRESTA_LEGACY_COOKIE_KEY="{args.cookie_key}"\n')
        print(f"[users] -> .env.fragment with PRESTA_LEGACY_COOKIE_KEY (do NOT commit)")


if __name__ == "__main__":
    main()
