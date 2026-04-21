import json
from datetime import datetime
# 引入你寫好的邏輯
from scanner import handle_message, monitor_data, stock_info_map

def run_mock_test():
    print("🧪 開始進行假資料模擬測試...")

    # 1. 人為設定測試標的資訊
    symbol = "2330"
    stock_info_map[symbol] = {
        "name": "台積電測試",
        "industry": "半導體",
        "themes": "模擬測試題材"
    }
    
    # 2. 人為設定 15 分鐘區間的高點 (假設高點是 600)
    monitor_data[symbol] = {
        "high": 600.0,
        "low": 590.0,
        "triggered": False
    }

    # 3. 模擬一筆「突破高點」的報價數據
    # 這裡我們模擬成交價是 605 (已突破 600)
    mock_quote = {
        "event": "data",
        "resource": "stock.intraday.quote",
        "data": {
            "symbol": symbol,
            "lastPrice": 605.0
        }
    }

    print(f"📡 模擬發送報價：{symbol} 現價 605.0 (突破點 600.0)")

    # 4. 強制執行判斷 (這裡要稍微注意時間判斷)
    # 蘇蘇提醒：因為 scanner.py 裡面有 datetime.now().time()
    # 如果你現在測試的時間不在 09:15~13:30，我們需要進去 scanner.py 暫時把時間判斷註解掉
    # 或者我們在這裡直接呼叫發送函數來測試 Line
    try:
        handle_message(mock_quote)
        print("✅ 模擬數據已處理，請檢查手機 Line 是否有反應！")
    except Exception as e:
        print(f"❌ 測試過程出錯: {e}")

if __name__ == "__main__":
    run_mock_test()