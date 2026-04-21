import os
from dotenv import load_dotenv
from fugle_marketdata import RestClient

# 1. 載入環境變數
load_dotenv()
FUGLE_API_KEY = os.getenv("FUGLE_API_KEY")

def test_fugle():
    # 2. 初始化富果客戶端
    client = RestClient(api_key=FUGLE_API_KEY)
    
    # 3. 嘗試抓取台積電 (2330) 的基本資料
    try:
        stock_info = client.stock.intraday.meta(symbol="2330")
        print("✅ 成功連線富果 API！")
        print(f"公司名稱: {stock_info.get('nameZh')}")
        print(f"產業類別: {stock_info.get('industryZh')}")
    except Exception as e:
        print(f"❌ 連線失敗，錯誤訊息: {e}")

if __name__ == "__main__":
    test_fugle()