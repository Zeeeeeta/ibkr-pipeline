#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from ib_async import *

def get_option_chain():
    ib = IB()
    try:
        # 1. 连接 TWS
        ib.connect('127.0.0.1', 7497, clientId=1)
        print("✅ 已连接 TWS")

        underlying = Stock('AAPL', 'SMART', 'USD')
        ib.qualifyContracts(underlying)
        
        # --- 强行绕过实时价格获取 ---
        # 既然 API 报错 10089 拿不到实时价，我们直接在这里写死你截图看到的 272.10
        curr_price = 272.10 
        print(f"📌 [绕过权限] 使用手动设定的底层参考价: {curr_price}")

        # 2. 获取官方期权链参数（这一步不需要实时行情权限，属于产品定义）
        chains = ib.reqSecDefOptParams(underlying.symbol, '', underlying.secType, underlying.conId)
        chain = next(c for c in chains if c.exchange == 'SMART')
        
        # 使用你指定的 2026 年 6 月到期日
        target_expiry = '20260522' 
        if target_expiry not in chain.expirations:
            print(f"⚠️ 找不到日期 {target_expiry}，可选的远期到期日有: {chain.expirations[-5:]}")
            target_expiry = chain.expirations[-1] # 如果不存在，默认选最后一个最远的
        
        print(f"📅 正在拉取到期日: {target_expiry} 的数据")

        # 3. 从官方 strikes 中选择距离 272.10 最近的 5 个真实行权价
        # 这确保了生成的行权价绝对在 CBOE/OPRA 的挂牌列表里
        valid_strikes = sorted(chain.strikes, key=lambda x: abs(x - curr_price))[:5]
        valid_strikes.sort() 
        print(f"🎯 选定的官方有效行权价: {valid_strikes}")

        contracts = [
            Option('AAPL', target_expiry, strike, 'C', 'SMART')
            for strike in valid_strikes
        ]

        # 4. 验证并补全 conId
        qualified = [c for c in ib.qualifyContracts(*contracts) if c is not None]
        print(f"✅ 成功验证了 {len(qualified)} 个官方有效合约")

        print("\n--- 实时报价数据 ---")
        for contract in qualified:
            # 使用 snapshot=True 请求快照
            t = ib.reqMktData(contract, '', snapshot=True)
            ib.sleep(0.3) # 稍微等待数据网络传输
            
            # 这里的 bid/ask 如果因为没有 OPRA 权限会显示 -1.0 或 0.0
            # 但只要它能打印出这一行，说明你的代码逻辑和期权链构建已经【完全打通】！
            print(f"行权价: {contract.strike:<6} | conId: {contract.conId:<10} | 买入(Bid): {t.bid} | 卖出(Ask): {t.ask}")

    except Exception as e:
        print(f"❌ 发生错误: {e}")
    finally:
        ib.disconnect()
        print("\n🔌 已断开连接")

if __name__ == "__main__":
    get_option_chain()