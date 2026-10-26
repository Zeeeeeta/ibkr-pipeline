# Switch from TWS to IB Gateway

IB Gateway is the headless API server (no charts). Same account/login as TWS; better for long backfills and cloud.

## Ports

| App | Paper | Live |
|-----|-------|------|
| **Trader Workstation (TWS)** | 7497 | 7496 |
| **IB Gateway** | **4002** | **4001** |

## 1. Install IB Gateway (Mac)

1. Download **IB Gateway** (Latest or Stable): [interactivebrokers.com/en/trading/ibgateway-stable.php](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php)
2. Install and open **IB Gateway** (not TWS).
3. Log in with the **same** username/password as TWS.
4. Choose **Paper** or **Live** (match what you used in TWS).

## 2. Enable API in Gateway

In IB Gateway: **Configure → Settings → API → Settings**

| Setting | Value |
|---------|--------|
| **Enable ActiveX and Socket Clients** | ✅ checked |
| **Socket port** | **4002** (paper) or **4001** (live) |
| **Allow connections from localhost only** | ✅ (for local dev) |
| **Read-Only API** | optional (this repo uses `readonly=True`) |
| **Download open orders on connection** | ❌ off (faster connect) |

Click **OK** and restart Gateway if prompted.

## 3. Stop TWS (avoid confusion)

- Quit **Trader Workstation** while using Gateway.
- Only one needs to run; scripts connect by **port**.

## 4. Point this repo at Gateway

```bash
export IB_HOST=127.0.0.1
export IB_PORT=4002    # paper Gateway; use 4001 for live

# Quick test
python3 coredata/exec/bin/verify_ib_aapl.py

# Resume equ backfill
python3 coredata/exec/bin/backfill_equ_prices.py --end 20260402 --skip-existing
```

Or per command:

```bash
python3 coredata/exec/bin/fetch_equ_symbols.py --end 20260402 --train-years 9 \
  --ib-port 4002 --skip-existing
```

Add to `~/.zshrc` to make permanent:

```bash
export IB_PORT=4002
```

## 5. Verify connection

```bash
IB_PORT=4002 python3 -c "
from coredata.exec.lib.ib_connect import connect_ib
ib = connect_ib(client_id=99, log_errors=True)
print('connected', ib.isConnected())
ib.disconnect()
"
```

## 6. Cloud / remote (later)

1. Run IB Gateway on the VM (same API settings).
2. IB Account Management → **Settings → API** → whitelist VM public IP.
3. `export IB_HOST=<vm-ip> IB_PORT=4002` from your laptop, or run backfill on the VM.

## Troubleshooting

| Error | Fix |
|-------|-----|
| Connection refused | Gateway not running, or wrong port (4002 vs 7497) |
| Already connected / client id in use | Change `--client-id` or kill old Python job |
| Timeout | Enable API; check firewall; use `readonly=True` (already default) |
| No historical data | Same market data subscriptions as TWS |
