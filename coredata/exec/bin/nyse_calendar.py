#!/usr/bin/env python3
import pandas as pd
from datetime import datetime
from pathlib import Path
from ib_insync import *

class NYSECalendar:
    def __init__(self, ib_instance=None, base_cache_dir: Path | None = None):
        self.ib = ib_instance
        if base_cache_dir is None:
            from lib.paths import COREDATA_DIR
            base_cache_dir = COREDATA_DIR / 'data' / 'trading_days'
        self.base_cache_dir = Path(base_cache_dir)
        self.base_cache_dir.mkdir(parents=True, exist_ok=True)

    def get_trading_days(self, start_date, end_date):
        """获取交易日列表，确保年份严格隔离"""
        start_dt = datetime.strptime(start_date, '%Y%m%d')
        end_dt = datetime.strptime(end_date, '%Y%m%d')
        
        all_cached_days = []
        # 遍历涉及的年份
        for year in range(start_dt.year, end_dt.year + 1):
            year_days = self._load_year_cache(year)
            # 如果本地没有该年数据，则同步
            if not year_days:
                print(f"📅 本地缺失 {year} 年日历，正在同步...")
                year_days = self._sync_year_from_api(year)
                # 再次过滤，确保存入该年文件的数据只属于该年
                year_days = [d for d in year_days if str(d).startswith(str(year))]
                self._save_year_cache(year, year_days)
            all_cached_days.extend(year_days)
            
        start_int, end_int = int(start_date), int(end_date)
        result = [str(d) for d in all_cached_days if start_int <= d <= end_int]
        return sorted(result)

    def _load_year_cache(self, year):
        # 命名修正: YYYY.trading_days.csv
        path = self.base_cache_dir / f"{year}.trading_days.csv"
        if path.exists():
            return pd.read_csv(path)['trading_day'].tolist()
        return []

    def _save_year_cache(self, year, days_list):
        path = self.base_cache_dir / f"{year}.trading_days.csv"
        # 强制过滤非该年份的数据，防止 IBKR 吐出的跨年数据污染
        filtered_days = [d for d in days_list if str(d).startswith(str(year))]
        pd.DataFrame(sorted(filtered_days), columns=['trading_day']).to_csv(path, index=False)

    def _sync_year_from_api(self, year):
        if not self.ib or not self.ib.isConnected():
            raise Exception(f"同步 {year} 日历需要 IB 连接")
            
        contract = Stock('AAPL', 'SMART', 'USD')
        current_year = datetime.now().year
        # 确定结束时间
        end_dt_str = f"{year}1231 23:59:59" if year < current_year else ""
            
        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime=end_dt_str,
            durationStr='1 Y',
            barSizeSetting='1 day',
            whatToShow='TRADES',
            useRTH=True
        )
        
        if not bars:
            return []
            
        df = util.df(bars)
        days = pd.to_datetime(df['date']).dt.strftime('%Y%m%d').astype(int).unique().tolist()
        return sorted(days)

    def calculate_duration_str(self, start_date, end_date):
        """计算自然日跨度"""
        s = datetime.strptime(start_date, '%Y%m%d')
        e = datetime.strptime(end_date, '%Y%m%d')
        diff = (e - s).days + 1
        return f"{max(diff, 1)} D"