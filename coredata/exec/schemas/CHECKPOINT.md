# OPCL checkpoint — review before production feature runs

## Sign-off

**Approved:** `proceed with reduced` (IB-only) — 2026-05-30

## Decisions

| Item | Value |
|------|-------|
| mk3 column names | **Confirmed** — prod `cboe_options_mk3` = `sid`, `optsid` + 86 CBOE v1.3 cols; `quote_date` is ISO `YYYY-MM-DD` |
| `strike_close == 1` (ATM, `_M1`) | Strike minimizing `abs(strike - prev_close)` per underlying-day |
| `dte == 1` (`_E1`) | `10 <= days_to_expire <= 60` (calendar days) |
| Model path | **Reduced** — price/OI signals only; no participant flow z-scores or `mm_total_qty` filter |
| Full model | Auto-selected when real mk3 flow data is on disk (`--full` to require) |
| z-score qty (full only) | Per bucket: `(sum buy qty) - (sum sell qty)` across open+close legs |

## Reduced feature set (IB-only)

Computed on `_all` bucket, broadcast to `_M1`/`_E1`, then cross-sectional rank:

| Signal | Source |
|--------|--------|
| `total_exchange_vol_signal_zscore` | Sum of col 14 across contracts |
| `open_interest_signal_zscore` | Sum of col 16 |
| `put_call_vol_imbalance_signal_zscore` | `(put_vol - call_vol) / (put_vol + call_vol + 1)` |

Each signal gets a 5-day rolling sum (`*_5day`).

## Local data paths

- IB options EOD: `coredata/data/prod/na/3.0/options_open_close/YYYY/MM/DD/YYYYMMDD.ib_options_eod.csv.gz`
- Equities: `coredata/data/price/YYYY/YYYYMMDD.equ_prices.csv`
- SOD output: `coredata/data/features/YYYY/YYYYMMDD.opcl.parq`

## Run

```bash
cd coredata/exec/bin

# With TWS running (real IB data):
python3 download_opt_history.py --test 5 --as-of YYYYMMDD --fetch-oi
python3 verify_ib_aapl.py   # quick hist bar check

# Dev / offline (no TWS) — synthetic volume/OI for pipeline smoke tests:
python3 seed_ib_options_eod.py --date YYYYMMDD

python3 build_sod_features.py --for-date YYYYMMDD          # auto reduced when IB-only
python3 build_sod_features.py --for-date YYYYMMDD --reduced  # explicit
python3 opcl_train_predict.py --for-date YYYYMMDD --train-days 60
```

**XGBoost on Mac:** needs `brew install libomp` or pipeline falls back to scikit-learn `HistGradientBoostingRegressor`.
