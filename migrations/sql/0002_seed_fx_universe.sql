-- FINZORA FX — seed reference data: FX universe + cross-asset instruments.
-- Applied directly to Neon alongside 0001_initial_schema.sql on 2026-08-19.
-- Purely additive reference data (currency_pairs, instruments) — required
-- before any price_data/signals/paper_trades rows can be inserted, since
-- those tables FK against instruments.

INSERT INTO currency_pairs (symbol, base_currency, quote_currency, category) VALUES
('EUR/USD','EUR','USD','MAJOR'),
('GBP/USD','GBP','USD','MAJOR'),
('USD/JPY','USD','JPY','MAJOR'),
('USD/CHF','USD','CHF','MAJOR'),
('AUD/USD','AUD','USD','MAJOR'),
('NZD/USD','NZD','USD','MAJOR'),
('USD/CAD','USD','CAD','MAJOR'),
('USD/SGD','USD','SGD','MAJOR'),
('EUR/GBP','EUR','GBP','CROSS'),
('EUR/JPY','EUR','JPY','CROSS'),
('GBP/JPY','GBP','JPY','CROSS'),
('AUD/JPY','AUD','JPY','CROSS'),
('NZD/JPY','NZD','JPY','CROSS'),
('EUR/CHF','EUR','CHF','CROSS'),
('GBP/CHF','GBP','CHF','CROSS'),
('AUD/NZD','AUD','NZD','CROSS'),
('EUR/AUD','EUR','AUD','CROSS'),
('GBP/AUD','GBP','AUD','CROSS'),
('EUR/CAD','EUR','CAD','CROSS'),
('GBP/CAD','GBP','CAD','CROSS');

INSERT INTO instruments (symbol, asset_class, display_name, is_tradeable, currency_pair_id)
SELECT symbol, 'FX', symbol, TRUE, id FROM currency_pairs;

INSERT INTO instruments (symbol, asset_class, display_name, is_tradeable) VALUES
('GOLD','COMMODITY','Gold Spot',FALSE),
('SILVER','COMMODITY','Silver Spot',FALSE),
('OIL_WTI','COMMODITY','WTI Crude Oil',FALSE),
('OIL_BRENT','COMMODITY','Brent Crude Oil',FALSE),
('DXY','INDEX','US Dollar Index',FALSE),
('SP500','INDEX','S&P 500',FALSE),
('NASDAQ','INDEX','Nasdaq Composite',FALSE),
('VIX','INDEX','CBOE Volatility Index',FALSE),
('US_10Y','BOND_YIELD','US 10-Year Treasury Yield',FALSE),
('DE_10Y','BOND_YIELD','German 10-Year Bund Yield',FALSE),
('UK_10Y','BOND_YIELD','UK 10-Year Gilt Yield',FALSE),
('JP_10Y','BOND_YIELD','Japan 10-Year JGB Yield',FALSE),
('AU_10Y','BOND_YIELD','Australia 10-Year Bond Yield',FALSE),
('CA_10Y','BOND_YIELD','Canada 10-Year Bond Yield',FALSE);
