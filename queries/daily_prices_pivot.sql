-- Daily metal prices (USD/toz) with gold converted to selected currencies.
-- Joins metal_prices with fx_rates on date.
-- rate_to_usd means: 1 unit of currency = rate_to_usd USD
-- so gold in currency = gold_usd / rate_to_usd
--
-- Usage: sqlite3 metals.db < queries/daily_prices_pivot.sql
--
-- Optional filters (edit before running):
--   WHERE mp.date BETWEEN '2018-02-01' AND '2018-04-30'
--   LIMIT 15

.mode column
.headers on
.width 12 12 12 12 10 14 12 12 12 14 12

SELECT
    mp.date,
    printf('$%.2f',  MAX(CASE WHEN mp.metal = 'gold'      THEN mp.price_usd END))                                                         AS gold_usd,
    printf('$%.2f',  MAX(CASE WHEN mp.metal = 'palladium' THEN mp.price_usd END))                                                         AS palladium,
    printf('$%.2f',  MAX(CASE WHEN mp.metal = 'platinum'  THEN mp.price_usd END))                                                         AS platinum,
    printf('$%.2f',  MAX(CASE WHEN mp.metal = 'silver'    THEN mp.price_usd END))                                                         AS silver,
    printf('₹%.2f',  MAX(CASE WHEN mp.metal = 'gold' THEN mp.price_usd END) / MAX(CASE WHEN fx.currency = 'INR' THEN fx.rate_to_usd END)) AS gold_inr,
--    printf('A$%.2f', MAX(CASE WHEN mp.metal = 'gold' THEN mp.price_usd END) / MAX(CASE WHEN fx.currency = 'AUD' THEN fx.rate_to_usd END)) AS gold_aud,
    printf('€%.2f',  MAX(CASE WHEN mp.metal = 'gold' THEN mp.price_usd END) / MAX(CASE WHEN fx.currency = 'EUR' THEN fx.rate_to_usd END)) AS gold_eur,
--    printf('£%.2f',  MAX(CASE WHEN mp.metal = 'gold' THEN mp.price_usd END) / MAX(CASE WHEN fx.currency = 'GBP' THEN fx.rate_to_usd END)) AS gold_gbp,
    printf('¥%.2f',  MAX(CASE WHEN mp.metal = 'gold' THEN mp.price_usd END) / MAX(CASE WHEN fx.currency = 'JPY' THEN fx.rate_to_usd END)) AS gold_jpy,
    printf('¥%.2f',  MAX(CASE WHEN mp.metal = 'gold' THEN mp.price_usd END) / MAX(CASE WHEN fx.currency = 'CNY' THEN fx.rate_to_usd END)) AS gold_cny
FROM metal_prices mp
JOIN fx_rates fx ON mp.date = fx.date
GROUP BY mp.date
ORDER BY mp.date
LIMIT 15;
