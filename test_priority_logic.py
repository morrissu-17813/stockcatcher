#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測試新的累積式優先級邏輯"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from stockcatcher.technical_indicator_engine import TechnicalSignalEngine
import pandas as pd

engine = TechnicalSignalEngine(api_key='test')
sample_df = pd.DataFrame([
    {'date': pd.Timestamp('2024-01-01'), 'open': 100.0, 'high': 105.0, 'low': 99.5, 'close': 103.5, 'volume': 2500},
    {'date': pd.Timestamp('2024-01-02'), 'open': 103.5, 'high': 107.0, 'low': 102.5, 'close': 106.0, 'volume': 3200},
    {'date': pd.Timestamp('2024-01-03'), 'open': 106.0, 'high': 110.0, 'low': 104.8, 'close': 109.4, 'volume': 4100},
    {'date': pd.Timestamp('2024-01-04'), 'open': 109.4, 'high': 114.0, 'low': 108.6, 'close': 113.2, 'volume': 5200},
])
feat_df = engine.add_technical_features(sample_df)
snapshot = engine.build_signal_snapshot('2330', feat_df)

# 調整 snapshot 以確保量能和技術條件都達到
snap_adjusted = dict(snapshot)
snap_adjusted['volume_ratio'] = 2.5  # 達到量能門檻
snap_adjusted['score'] = 60.0        # 達到技術門檻
snap_adjusted['is_3k_breakout'] = True  # 日線多頭條件
snap_adjusted['rsi14'] = 55.0        # RSI > 50
snap_adjusted['macd_hist'] = 0.5     # MACD > 0

print("=" * 60)
print("【新的累積式優先級邏輯測試】")
print("=" * 60)

# 測試 Tier 1: 基礎條件 (量能 + 技術)
print('\n✓ Test 1: Tier 1 基礎觸發 (量能2.5x + 技術60分)\n')
chip = {'foreign': 0, 'investment': 0, 'dealer': 0, 'big_holder': 100, 'net_buy': 0}
insider = {'net_buy': 0, 'buy_count': 0, 'buy_streak': 0, 'annotation': '買超'}
decision = engine.evaluate_alert_triggers('2330', snapshot=snap_adjusted, chip=chip, insider=insider)
print(f"  Tier Level: {decision['tier_level']}")
print(f"  Should Send: {decision['should_send']}")
print(f"  Tier1Base: {decision['tier1_base']}")
print(f"  Trigger Reason: {decision['trigger_reason']}\n")
message = engine.build_trigger_message('2330', snapshot=snap_adjusted, chip=chip, insider=insider)
print("通知訊息:")
print(message)

# 測試 Tier 2: 進階 (Tier1 + 內部人買超)
print('\n\n✓ Test 2: Tier 2 進階觸發 (加上內部人買超)\n')
insider = {'net_buy': 5000, 'buy_count': 1, 'buy_streak': 1, 'annotation': '買超'}
decision = engine.evaluate_alert_triggers('2330', snapshot=snap_adjusted, chip=chip, insider=insider)
print(f"  Tier Level: {decision['tier_level']}")
print(f"  Should Send: {decision['should_send']}")
print(f"  Tier2Advanced: {decision['tier2_advanced']}")
print(f"  Trigger Reason: {decision['trigger_reason']}\n")
message = engine.build_trigger_message('2330', snapshot=snap_adjusted, chip=chip, insider=insider)
print("通知訊息:")
print(message)

# 測試 Tier 3: 終極 (Tier2 + 大戶 + 連買)
print('\n\n✓ Test 3: Tier 3 終極觸發 (加上大戶400張+連買)\n')
chip = {'foreign': 150, 'investment': 100, 'dealer': 50, 'big_holder': 500, 'net_buy': 800}
insider = {'net_buy': 5000, 'buy_count': 3, 'buy_streak': 3, 'annotation': '連買'}
decision = engine.evaluate_alert_triggers('2330', snapshot=snap_adjusted, chip=chip, insider=insider)
print(f"  Tier Level: {decision['tier_level']}")
print(f"  Should Send: {decision['should_send']}")
print(f"  Tier3Ultimate: {decision['tier3_ultimate']}")
print(f"  IsConsecutiveBuy: {decision['is_consecutive_buy']}")
print(f"  Trigger Reason: {decision['trigger_reason']}\n")
message = engine.build_trigger_message('2330', snapshot=snap_adjusted, chip=chip, insider=insider)
print("通知訊息:")
print(message)

# 測試不符合任何條件
print('\n\n✗ Test 4: 不符合任何條件 (量能和技術都不足)\n')
chip = {'foreign': 0, 'investment': 0, 'dealer': 0, 'big_holder': 100, 'net_buy': 0}
insider = {'net_buy': 0, 'buy_count': 0, 'buy_streak': 0, 'annotation': '買超'}
snap_low = dict(snapshot)
snap_low['volume_ratio'] = 1.5  # 低於門檻
snap_low['score'] = 40.0         # 低於門檻
decision = engine.evaluate_alert_triggers('2330', snapshot=snap_low, chip=chip, insider=insider)
print(f"  Tier Level: {decision['tier_level']}")
print(f"  Should Send: {decision['should_send']}")
print(f"  Trigger Reason: {decision['trigger_reason']}\n")

# 測試 Tier2 但無連買 (不符合 Tier3)
print('\n✓ Test 5: Tier 2 達成但無連買 (不達 Tier3)\n')
chip = {'foreign': 150, 'investment': 100, 'dealer': 50, 'big_holder': 500, 'net_buy': 800}
insider = {'net_buy': 5000, 'buy_count': 1, 'buy_streak': 1, 'annotation': '買超'}
decision = engine.evaluate_alert_triggers('2330', snapshot=snap_adjusted, chip=chip, insider=insider)
print(f"  Tier Level: {decision['tier_level']}")
print(f"  Should Send: {decision['should_send']}")
print(f"  Tier2Advanced: {decision['tier2_advanced']}")
print(f"  Tier3Ultimate: {decision['tier3_ultimate']}")
print(f"  IsConsecutiveBuy: {decision['is_consecutive_buy']}")
print(f"  Trigger Reason: {decision['trigger_reason']}\n")
message = engine.build_trigger_message('2330', snapshot=snap_adjusted, chip=chip, insider=insider)
print("通知訊息:")
print(message)

print("\n" + "=" * 60)
print("✅ 所有測試完成")
print("=" * 60)

