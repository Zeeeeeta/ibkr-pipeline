#!/usr/bin/env python3
from ib_insync import *

def final_attempt():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=999)
        # 订阅后一定要设置为实时模式 1
        ib.reqMarketDataType(1) 

        print("🔍 探测到一个【绝对活跃】的平值合约...")
        underlying = Stock('AAPL', 'SMART', 'USD')
        ib.qualifyContracts(underlying)
        
        # 1. 找一个平值(ATM)合约，这是最容易有数据的
        test_opt = Option('AAPL', '20260619', 170.0, 'C', 'SMART') 
        ib.qualifyContracts(test_opt)
        print(f"🎯 验证通过: {test_opt.localSymbol}")

        # 2. 依次尝试三种数据类型
        modes = ['TRADES', 'BID_ASK', 'MIDPOINT']
        success = False

        for mode in modes:
            print(f"📊 正在尝试拉取模式: {mode} ...")
            bars = ib.reqHistoricalData(
                test_opt, 
                endDateTime='', 
                durationStr='10 D', # 跨度长一点，确保包含上周五
                barSizeSetting='1 day', 
                whatToShow=mode, 
                useRTH=True
            )
            
            if bars:
                print(f"🎉 🎉 🎉 {mode} 模式大获成功！拿到 {len(bars)} 条数据。")
                print(f"最近收盘价: {bars[-1].close}")
                success = True
                break
            else:
                print(f"❌ {mode} 模式在服务器中无记录。")

        if not success:
            print("\n🚨 警报：所有模式均无数据。")
            print("请检查：TWS 里的 AAPL 期权链是否有实时变动的【买入价/卖出价】？")
            print("如果 TWS 里也是空的（横线），那说明订阅还未生效，建议重启 TWS。")

    except Exception as e:
        print(f"🚨 出错: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    final_attempt()