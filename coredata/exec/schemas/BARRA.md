# Barra USFASTD reference docs

## In repo

| File | Description |
|------|-------------|
| [barra_us_tmt_factor_details_2015.pdf](barra_us_tmt_factor_details_2015.pdf) | *Factor Details* (Mar 2015) |
| [barra_us_tmt_descriptor_details_2015.pdf](barra_us_tmt_descriptor_details_2015.pdf) | *Descriptor Details* — 66 descriptors, formulas |
| [barra_industry_keywords.csv](../../data/ref/barra_industry_keywords.csv) | Keyword → `usfastd_*` (fallback) |
| `gics_industries.py` | 60 GICS industry labels → `usfastd_*` slugs |

## Official mk4 on disk (prod copy)

```
coredata/data/prod/na/3.0/barra/2026/
  20260401.usfastd_rsk.rev.mk4.csv.gz
  20260402.usfastd_rsk.rev.mk4.csv.gz
  20260406 … 20260409
```

Loaded by `mk4_loader.py` (comma-separated CSV). **Calibration only** — not a daily production feed.

## Tier 1 prod inputs (user-provided)

| Item | Location | Notes |
|------|----------|--------|
| mk4 files | `Downloads/2026040*.usfastd_rsk.rev.mk4.csv.gz` → copied to `barra/2026/` | ~5.3k rows/day; `estu=1` ≈ 2180 (MSCI USA IMI) |
| Prod returns | `Downloads/2026040*.data.parquet` | `tid`, `rtn_*`, `res_rtn_*`, `qbt_mkt_cap`; use hour **16** for close |
| ESTU | MSCI **USA IMI** constituents | `estu` column in mk4; IMI methodology: `Downloads/664204_20260603.zip` |
| Capitalization | Last trading day **market value of common equity** | mk4 `capitalization`; Size = ln(cap); sqrt(cap) GLS weights |
| Industries | 60 GICS names (USFASTD) | See `gics_industries.py`; mk4 uses `indname1..5` / `wgt1..5` |

## Key formulas (Descriptor Details)

| Factor | Spec |
|--------|------|
| **Size** | LNCAP = ln(market cap) |
| **Mid cap** | Cube of standardized size → orthogonalize to size |
| **Momentum** | RSTR: 504d, lag 20d, half-life 126 |
| **Liquidity** | STOM = ln(monthly share turnover) |
| **Beta** | HBETA: 252d, half-life 63, cap-weighted ESTU market |

## Equ price backfill (Path B)

Old equ files were **15-symbol** IB probes; full universe (~1,688) only exists for a short 2026 window. Backfill **9 years** before building Lean Barra history:

```bash
# Full universe, 9y (caffeinate keeps Mac awake; keep IB Gateway logged in)
IB_PORT=4002 python3 coredata/exec/bin/backfill_equ_prices.py --end 20260402

# Resume after interrupt
python3 coredata/exec/bin/backfill_equ_prices.py --end 20260402 --skip-existing

# Batch
python3 coredata/exec/bin/backfill_equ_prices.py --end 20260402 --offset 0 --limit 200
```

Progress: `coredata/data/ref/equ_backfill_progress.csv`  
Log: `coredata/data/ref/equ_backfill.log`

After backfill, build Lean with enough history for RSTR (504d):

```bash
python3 coredata/exec/bin/build_lean_barra.py --for-date 20260402 --history-days 1100
```

## Tooling

```bash
# Build Lean exposures (fallback when no mk4)
python3 coredata/exec/bin/build_lean_barra.py --for-date 20260402

# Compare Lean vs official mk4 styles
python3 coredata/exec/bin/compare_barra_exposures.py --for-date 20260402 --tickers PLD,AKR,ACM

# Full calibration report (sample mk4 week)
python3 coredata/exec/bin/calibrate_lean_barra.py --for-date 20260402 --rebuild --tickers PLD,AMN,AKR,ACM,AAPL

# Compare replicated vs prod residuals (requires mk4 + prod parquet)
python3 coredata/exec/bin/validate_barra_residuals.py --for-date 20260402 --tickers PLD,AKR,ACM,AAPL \
  --prod-data-dir $HOME/Downloads
```

## Recommended production path

1. **Build daily Lean exposures** (`build_lean_barra.py`) from equ prices + universe screener (+ FMP fundamentals for value).
2. **Residualization / features:** `labels.py` uses **Lean parquet** by default; set `LEAN_BARRA_USE_OFFICIAL=1` only for QA against sample mk4.
3. **ESTU:** Lean flags an ESTU proxy (large, liquid names); GLS in `residualize.py` filters `estu == 1`.
4. **Calibration:** compare Lean vs sample mk4 with `calibrate_lean_barra.py`; close gaps (cap, ESTU z-score, descriptors) until RMSE/corr targets are met.

## Known Lean vs Barra gaps (minimize via calibration)

| Area | Barra | Lean (current) |
|------|-------|----------------|
| Universe | ~5.3k coverage, ~2.2k ESTU (IMI) | Screener ~1.7k; ESTU proxy |
| Cap | Last-day common equity | `close × (screener_cap / last_sale)` |
| Cross-section | ESTU-weighted MAD/z | ESTU-weighted (proxy) |
| Value | BTOP + composites | FMP book/EPS when keyed |
| Styles | earnqlty, mgmtqlty, … | Zeroed until data source exists |

## Still optional

- Full **USA IMI constituent list** (from `664204_20260603.zip`) to flag ESTU in Lean-only mode
- `test.md` prod notes (path not found in workspace — paste into `schemas/` if useful)
