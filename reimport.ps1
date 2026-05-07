# Full re-import: drop DB, let Liquibase rebuild schema, run all transforms,
# load all SQL. Use this any time you change schema yaml mid-development —
# faster than wrestling backups + Liquibase checksums.
#
# Pre-reqs:
#   - docker stack up (postgres, redis, vault, eshop-app)
#   - Presta CSVs in C:\Users\Ioana Dinu\Downloads (or path you adjust below)
#   - Cookie key set (replace below)
#
# Total runtime: ~3-5 minutes start-to-finish.

$ErrorActionPreference = "Stop"

$migrationRepo = "C:\Users\Ioana Dinu\IdeaProjects\e-shop.tech_migration_tools"
$downloads     = "C:\Users\Ioana Dinu\Downloads"
$cookieKey     = "rbg7w2zenoc9xagpuhqljrr3e8ybmo14qawxpncgqcqv44en1urww96b"
$adminEmail    = "ioana.dinu.it@gmail.com"

Write-Host "=== 1. Drop + recreate database ===" -ForegroundColor Cyan
docker exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS eshop;"
docker exec postgres psql -U postgres -c "CREATE DATABASE eshop;"

Write-Host "=== 2. Restart eshop-app so Liquibase rebuilds schema ===" -ForegroundColor Cyan
docker compose restart eshop-app
Write-Host "Waiting for eshop-app to be healthy..."
$maxWait = 180
$elapsed = 0
do {
    Start-Sleep -Seconds 5
    $elapsed += 5
    $health = docker compose ps eshop-app --format '{{.Health}}' 2>$null
    Write-Host "  ...$elapsed seconds, health=$health"
} while ($health -ne "healthy" -and $elapsed -lt $maxWait)

if ($health -ne "healthy") {
    Write-Host "App didn't become healthy in $maxWait seconds. Bail." -ForegroundColor Red
    exit 1
}

Write-Host "=== 3. Import users (4895 rows expected) ===" -ForegroundColor Cyan
Set-Location $migrationRepo
python scripts/transform_users.py `
    --customers-csv "$downloads\ps_country_lang.csv" `
    --out ./ready `
    --cookie-key $cookieKey
Get-Content ./ready/users.sql -Raw | docker exec -i postgres psql -U postgres -d eshop -v ON_ERROR_STOP=1

Write-Host "=== 4. Normalize names + fix email typos ===" -ForegroundColor Cyan
@"
UPDATE "user"
SET first_name = INITCAP(REGEXP_REPLACE(TRIM(first_name), '\?+', 'u', 'g')),
    last_name  = INITCAP(REGEXP_REPLACE(TRIM(last_name),  '\?+', 'u', 'g'));

WITH typo_map(typo, canonical) AS (VALUES
    ('uahoo.com','yahoo.com'),('yahoo.cim','yahoo.com'),('yahoo.con','yahoo.com'),
    ('yahoo.cpm','yahoo.com'),('yahoo.comp','yahoo.com'),('yahoo.co','yahoo.com'),
    ('yhoo.com','yahoo.com'),('yahooo.ro','yahoo.ro'),
    ('gamail.com','gmail.com'),('gamil.com','gmail.com'),('gmai.com','gmail.com'),
    ('gmail.cim','gmail.com'),('gmail.comi','gmail.com'),('gmail.con','gmail.com'),
    ('gmail.vom','gmail.com'),('rocketmail.con','rocketmail.com'),
    ('freemai.hu','freemail.hu'),('biorganicbubu.roo','biorganicbubu.ro'),
    ('ulbaibiu.ro','ulbsibiu.ro')
)
UPDATE "user" u
SET email = SPLIT_PART(u.email,'@',1) || '@' || tm.canonical
FROM typo_map tm
WHERE LOWER(SPLIT_PART(u.email,'@',2)) = tm.typo;

UPDATE authentication a SET username = u.email FROM "user" u
WHERE a.user_id = u.user_id AND a.username <> u.email;
"@ | docker exec -i postgres psql -U postgres -d eshop -v ON_ERROR_STOP=1

Write-Host "=== 5. Import reviews (~1892 rows expected) ===" -ForegroundColor Cyan
python scripts/transform_reviews.py `
    --reviews-csv "$downloads\p (1).csv" `
    --out ./ready
Get-Content ./ready/product_feedback.sql -Raw | docker exec -i postgres psql -U postgres -d eshop -v ON_ERROR_STOP=1

Write-Host "=== 6. Seed top sellers from biorganicbubu ===" -ForegroundColor Cyan
# (Adjust seed_top_sellers args if you have a fresh CSV)
if (Test-Path ./exports/biorganicbubu_top_all.csv) {
    python scripts/seed_top_sellers.py `
        --codes-csv ./exports/biorganicbubu_top_all.csv `
        --admin-email $adminEmail `
        --out ./ready `
        --target-count 30
    Get-Content ./ready/top_sellers.sql -Raw | docker exec -i postgres psql -U postgres -d eshop -v ON_ERROR_STOP=1
} else {
    Write-Host "  (skipped — biorganicbubu_top_all.csv missing)" -ForegroundColor Yellow
}

Write-Host "=== 7. Bootstrap shop_details + invoicing ===" -ForegroundColor Cyan
if (Test-Path ./sql/seed/10-biotu-bootstrap.sql) {
    Get-Content ./sql/seed/10-biotu-bootstrap.sql -Raw | docker exec -i postgres psql -U postgres -d eshop -v ON_ERROR_STOP=1
}

Write-Host "=== 8. Flush Redis ===" -ForegroundColor Cyan
docker exec redis redis-cli -a your_password FLUSHALL

Write-Host "=== Final counts ===" -ForegroundColor Green
@"
SELECT 'users'       AS what, COUNT(*) FROM "user"
UNION ALL SELECT 'reviews',     COUNT(*) FROM product_feedback
UNION ALL SELECT 'orders',      COUNT(*) FROM "order"
UNION ALL SELECT 'order_lines', COUNT(*) FROM order_product
UNION ALL SELECT 'shop_rows',   COUNT(*) FROM shop_details;
"@ | docker exec -i postgres psql -U postgres -d eshop

Write-Host "DONE." -ForegroundColor Green
