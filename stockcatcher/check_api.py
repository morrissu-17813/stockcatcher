import os
from fugle_marketdata import RestClient
from dotenv import load_dotenv
import json

load_dotenv()
api_key = os.getenv("FUGLE_API_KEY")

def diagnostic_fugle():
    if not api_key:
        print("❌ 錯誤：找不到 API Key")
        return

    rest_client = RestClient(api_key=api_key)
    symbol = "2313"
    
    try:
        print(f"🔍 正在抓取 {symbol} 的 Ticker 資訊...")
        
        # 💡 [關鍵修正]：將 .meta() 改為 .ticker()
        # 這是富果 Market Data API v1 獲取基本資訊的標準指令
        data = rest_client.stock.intraday.ticker(symbol=symbol)
        
        print("\n=== [API 原始回傳內容] ===")
        print(json.dumps(data, indent=4, ensure_ascii=False))
        print("=========================\n")

        # 驗證欄位
        name = data.get("nameZh")
        industry = data.get("industryZh")
        
        if name:
            print(f"✅ 成功抓到名稱：{name}")
            print(f"✅ 成功抓到產業：{industry}")
        else:
            print(f"⚠️ API 成功回傳，但找不到 'nameZh'。請檢查上方原始內容中的鍵值名稱。")

    except Exception as e:
        print(f"❌ 發生異常：{e}")
        print("\n💡 蘇蘇提示：如果還是報錯，代表可能是 rest_client.stock.intraday.meta(symbol=symbol) ")
        print("或是 SDK 版本結構與預期不同。")

if __name__ == "__main__":
    diagnostic_fugle()