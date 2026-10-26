# IB mimic matrix — CBOE Open/Close EOD cols 1–86

Spec: [Open_Close_EOD_Spec_v1.3.pdf](https://datashop.cboe.com/documents/Open_Close_EOD_Spec_v1.3.pdf)

Probe artifacts: `ib_probe_results.json`, `ib_flow_probe_results.json` (from `probe_ib_options_hist.py`, `probe_ib_flow.py`)

## Connection notes (local TWS port 7497)

- Use `fetchFields=StartupFetchNONE` and `readonly=True` to avoid 20s+ account sync timeouts.
- `reqSecDefOptParams` requires valid underlying **conId** (not 0); use [symbol_conid.py](../lib/symbol_conid.py).
- Avoid `qualifyContracts` in bulk; it often hits `RequestTimeout`.
- Enable `log_errors=True` on connect; do not swallow API errors during diagnostics.

## Summary

| Col range | IB mimic | Notes |
|-----------|----------|-------|
| 1–9 metadata | **Yes** | From contract + quote date |
| 10–13 OHLC | **Partial** | `reqHistoricalData` TRADES/MIDPOINT 1h→1d; often 0 bars or timeout without options hist entitlement |
| 14 `total_exchange_vol` | **Partial** | Sum of bar `volume` when bars exist |
| 15–18 industry vol / OI / prev | **Partial** | Generic tick 101 snapshot for OI; prev from prior bar |
| 19–86 flow | **No** | Requires CBOE trade origin codes (F/B/M/C/U/W); IB has no open/close × participant × size bucket |

## Flow columns (19–86) — all **No**

| Bucket | Columns | IB field | Verdict |
|--------|---------|----------|---------|
| firm | 19–26 | — | No |
| bd | 27–34 | — | No |
| mm | 35–38 | — | No |
| cust lt_100 / 100_199 / gt_199 | 39–62 | — | No |
| procust lt_100 / 100_199 / gt_199 | 63–86 | — | No |

Generic tick 100 (call/put volume) is chain-level, not per-contract, and not open/close classified.

## OPCL feature impact

| Requirement | Needs | With IB-only |
|-------------|-------|--------------|
| `mm_total_qty` filter | mm_buy_qty + mm_sell_qty | Fails / all zero |
| firm/bd/cust z-scores | flow qty cols | Fails / degenerate |
| `_M1` ATM aggregate | strike_close + flow | strike_close OK; flow zero |
| `_E1` DTE 10–60 | days_to_expire + flow | DTE OK; flow zero |

**Recommendation:** use real `cboe_options_mk3.csv.gz` for production parity; keep `ib_options_eod.csv.gz` for OHLC/OI skeleton and testing.

## Historical data probe checklist

Run with TWS up:

```bash
cd coredata/exec/bin
python3 verify_ib_aapl.py
python3 probe_ib_options_hist.py --symbol AAPL --client-id 103
python3 probe_ib_flow.py --symbol AAPL --client-id 104
```

Expected errors when hist unavailable: 162 (pacing), 321 (bad conId), 366 (no historical query), historical timeout.

Last `verify_ib_aapl.py` run: secdef OK; TRADES/MIDPOINT/BID_ASK all returned 0 bars with IB 366.
