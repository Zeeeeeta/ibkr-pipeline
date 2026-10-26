#!/usr/bin/env python3
import sys
import time
import argparse
import pandas as pd
from pathlib import Path
from ib_insync import *

REPO_ROOT = Path(__file__).resolve().parents[3]
LIB_PATH = str(Path(__file__).resolve().parent)
if LIB_PATH not in sys.path:
    sys.path.append(LIB_PATH)

from nyse_calendar import NYSECalendar

# Local data lake. These directories are not part of the public repository.
SCREENER_PATH = REPO_ROOT / "coredata" / "data" / "univ" / "2026" / "na_exch_screener_0418.csv"
BASE_DATA_DIR = REPO_ROOT / "coredata" / "data" / "price"
COLUMNS = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'average', 'barCount']
# ==========================================

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--start_date", type=str, required=True)
    parser.add_argument("-e", "--end_date", type=str, required=True)
    parser.add_argument("--test", type=int, default=None)
    return parser.parse_args()

def main():
    args = get_args()
    ib = IB()
    
    try:
        ib.connect('127.0.0.1', 7497, clientId=200)
        ib.reqMarketDataType(3)

        cal = NYSECalendar(ib)
        # 1. 获取精准交易日
        trading_days = cal.get_trading_days(args.start_date, args.end_date)
        
        if not trading_days:
            print("❌ 无效交易日范围")
            return
        
        # 2. 调用已修复的成员方法
        duration = cal.calculate_duration_str(args.start_date, args.end_date)
        ib_end_time = f"{args.end_date} 23:59:59"

        screener_df = pd.read_csv(SCREENER_PATH)
        symbols = screener_df['Symbol'].dropna().unique().tolist()
        if args.test:
            symbols = symbols[:args.test]

        print(f"🚀 开始同步，目标交易日: {len(trading_days)} 天")

        for i, symbol in enumerate(symbols):
            print(f"进度: [{i+1}/{len(symbols)}] 正在处理 {symbol}...", end='\r')
            
            try:
                contract = Stock(symbol, 'SMART', 'USD')
                bars = ib.reqHistoricalData(
                    contract, endDateTime=ib_end_time, durationStr=duration,
                    barSizeSetting='1 day', whatToShow='TRADES', useRTH=True
                )

                if bars:
                    df = util.df(bars)
                    df.insert(0, 'symbol', symbol)
                    df['date_str'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
                    
                    # 精确过滤
                    df = df[df['date_str'].isin(trading_days)].copy()
                    
                    if not df.empty:
                        for date_str, group in df.groupby('date_str'):
                            year = date_str[:4]
                            save_path = BASE_DATA_DIR / year / f"{date_str}.equ_prices.csv"
                            save_path.parent.mkdir(parents=True, exist_ok=True)
                            
                            output = group[COLUMNS]
                            if not save_path.exists():
                                output.to_csv(save_path, index=False)
                            else:
                                output.to_csv(save_path, mode='a', index=False, header=False)
                
                time.sleep(0.3)

            except Exception as e:
                continue

    finally:
        ib.disconnect()
        print(f"\n✅ 任务结束。日历已按年隔离并存入 data/trading_days/ ")

if __name__ == "__main__":
    main()