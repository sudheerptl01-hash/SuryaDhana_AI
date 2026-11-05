# NSE panel spot-check 2010–2019 (classic CM bhavcopy era)

Panel 2010-01-01 → 2019-09-30: 2,419 sessions × 2,383 symbols; corporate actions applied in this era: 2,120 ({'gap_heuristic': 1791, 'yahoo_split': 302, 'yahoo_confirmed_raw': 21, 'gap_heuristic_yahoo_name': 6})

Sample: 46 liquid stocks compared with Yahoo's live history (106,507 daily returns).
- Days differing by > 5 points: **31** (0.029%)
- Days differing by > 20 points (missed or wrong split/bonus): **5**
- Median total-return gap NSE vs Yahoo over the decade: 36.1% (Yahoo includes dividends)

Large disagreements (symbol, date, NSE return, Yahoo return):

- ('SUVEN', datetime.date(2011, 8, 1), -0.018, 0.325)
- ('SUVEN', datetime.date(2012, 9, 17), -0.017, 0.32)
- ('SUVEN', datetime.date(2013, 8, 1), 0.009, 0.361)
- ('SUVEN', datetime.date(2014, 7, 24), -0.027, 0.715)
- ('SUVEN', datetime.date(2016, 3, 14), 0.017, 0.267)