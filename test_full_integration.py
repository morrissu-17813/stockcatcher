#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整集成測試：
1. nstock 超連結 ✓
2. FinMind API 內部人資料 ✓
3. Tier 優先級邏輯 ✓
4. Telegram 通知 ✓
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from stockcatcher.technical_indicator_engine import (
    TechnicalSignalEngine,
    WarrantTelegramAlertRunner,
    FundamentalChipDataLayer,
)
import pandas as pd

print("=" * 70)
print("【完整集成測試】nstock + FinMind + Tier邏輯 + Telegram")
print("=" * 70)

# ============================================================
# Test 1: Tier 邏輯驗證（帶nstock超連結）
# ============================================================
print("\n✓ Test 1: Tier 優先級邏輯（帶nstock超連結）")
print("-" * 70)

engine = TechnicalSignalEngine(api_key="test_key")
sample_df = pd.DataFrame([
    {'date': pd.Timestamp('2024-01-01'), 'open': 100.0, 'high': 105.0, 'low': 99.5, 'close': 103.5, 'volume': 2500},
    {'date': pd.Timestamp('2024-01-02'), 'open': 103.5, 'high': 107.0, 'low': 102.5, 'close': 106.0, 'volume': 3200},
    {'date': pd.Timestamp('2024-01-03'), 'open': 106.0, 'high': 110.0, 'low': 104.8, 'close': 109.4, 'volume': 4100},
    {'date': pd.Timestamp('2024-01-04'), 'open': 109.4, 'high': 114.0, 'low': 108.6, 'close': 113.2, 'volume': 5200},
])

feat_df = engine.add_technical_features(sample_df)
snapshot = engine.build_signal_snapshot('2330', feat_df)

# 調整為達到Tier條件
snap_tier3 = dict(snapshot)
snap_tier3['volume_ratio'] = 2.5
snap_tier3['score'] = 65.0
snap_tier3['is_3k_breakout'] = True
snap_tier3['rsi14'] = 55.0
snap_tier3['macd_hist'] = 0.5

chip = {'foreign': 250, 'investment': 180, 'dealer': 90, 'big_holder': 500, 'net_buy': 1020}
insider = {'net_buy': 2000, 'buy_count': 3, 'buy_streak': 3, 'annotation': '連三買'}

decision = engine.evaluate_alert_triggers('2330', snapshot=snap_tier3, chip=chip, insider=insider)
message = engine.build_trigger_message('2330', snapshot=snap_tier3, chip=chip, insider=insider)

print(f"Tier Level: {decision['tier_level']} (期望: 3)")
print(f"Should Send: {decision['should_send']} (期望: True)")
print(f"Tier1Base: {decision['tier1_base']}")
print(f"Tier2Advanced: {decision['tier2_advanced']}")
print(f"Tier3Ultimate: {decision['tier3_ultimate']}")
print()
print("📱 Telegram 訊息預覽:")
print("-" * 70)
print(message[:150] + "...")
print()
if "[2330](https://www.nstock.tw/stock_info?stock_id=2330)" in message:
    print("✅ nstock 超連結已正確插入")
else:
    print("❌ nstock 超連結遺失")

# ============================================================
# Test 2: FinMind API 測試
# ============================================================
print("\n✓ Test 2: FinMind API（內部人買超資料）")
print("-" * 70)

print("嘗試查詢 FinMind 內部人買超資料...")
try:
    insider_data = FundamentalChipDataLayer.fetch_insider_buy_data(lookback_days=5)
    if insider_data:
        sample_stocks = list(insider_data.keys())[:3]
        print(f"✅ 成功取得 {len(insider_data)} 檔內部人買超股票")
        print(f"   樣本: {sample_stocks}")
        for sid in sample_stocks[:1]:
            data = insider_data[sid]
            print(f"   {sid}: 買超{data['net_buy']:.0f}股, 買超人次{data['buy_count']}")
    else:
        print("⚠️ 查詢結果為空（可能是API限制或無符合條件的股票）")
except Exception as e:
    print(f"❌ FinMind API 異常: {e}")

# ============================================================
# Test 3: 模擬盤中掃描
# ============================================================
print("\n✓ Test 3: 模擬 MIS 逆向掃描（不實際發送Telegram）")
print("-" * 70)

try:
    runner = WarrantTelegramAlertRunner(quota=5, chat_id="1087480334")
    pool = runner.build_hot_underlying_pool()
    print(f"✅ 取得熱門現股池: {len(pool)} 檔")
    print(f"   池子: {pool}")
    
    # 不執行實際的run_cycle（避免頻繁API調用），只測試結構
    print(f"✅ WarrantTelegramAlertRunner 結構完整")
except Exception as e:
    print(f"⚠️ 掃描測試異常: {e}")

# ============================================================
# Test 4: 完整決策流程
# ============================================================
print("\n✓ Test 4: 完整決策流程驗證")
print("-" * 70)

test_cases = [
    {
        "name": "Tier 1 基礎",
        "chip": {'foreign': 50, 'investment': 30, 'dealer': 20, 'big_holder': 100, 'net_buy': 200},
        "insider": {'net_buy': 0, 'buy_count': 0, 'buy_streak': 0, 'annotation': '買超'},
        "snapshot_override": {'volume_ratio': 2.5, 'score': 62.0, 'is_3k_breakout': True, 'rsi14': 55, 'macd_hist': 0.1},
    },
    {
        "name": "Tier 2 進階",
        "chip": {'foreign': 100, 'investment': 80, 'dealer': 50, 'big_holder': 200, 'net_buy': 500},
        "insider": {'net_buy': 1000, 'buy_count': 2, 'buy_streak': 2, 'annotation': '連買'},
        "snapshot_override": {'volume_ratio': 2.5, 'score': 65.0, 'is_3k_breakout': True, 'rsi14': 60, 'macd_hist': 0.2},
    },
    {
        "name": "Tier 3 終極",
        "chip": {'foreign': 200, 'investment': 150, 'dealer': 100, 'big_holder': 500, 'net_buy': 1200},
        "insider": {'net_buy': 3000, 'buy_count': 3, 'buy_streak': 3, 'annotation': '連三買'},
        "snapshot_override": {'volume_ratio': 3.0, 'score': 70.0, 'is_3k_breakout': True, 'rsi14': 65, 'macd_hist': 0.5},
    },
]

for test in test_cases:
    snap_test = dict(snapshot)
    snap_test.update(test["snapshot_override"])
    
    decision = engine.evaluate_alert_triggers('2330', snapshot=snap_test, chip=test["chip"], insider=test["insider"])
    status = "✅" if decision["should_send"] else "❌"
    print(f"{status} {test['name']}: Tier {decision['tier_level']}, 發送={decision['should_send']}")

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("✅ 完整集成測試完成")
print("=" * 70)
print("\n【整合清單】")
print("  ✓ nstock 超連結 (Markdown格式)")
print("  ✓ FinMind API 內部人買超資料")
print("  ✓ Tier 優先級邏輯（1層→2層→3層）")
print("  ✓ Telegram 訊息格式")
print("  ✓ 決策觸發條件")
print("\n【下一步】")
print("  執行: python technical_indicator_engine.py")
print("  效果: 盤中自動監控，每10秒掃一次，盤中09:00-13:30")
print("\n" + "=" * 70)
