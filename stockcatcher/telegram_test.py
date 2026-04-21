import os
import requests
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_tg_alert(stock_id, trend, price, limit_price, stop_loss, industry, themes):
    """
    發送精美的 Telegram 通知
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 錯誤：找不到 Telegram Token 或 Chat ID")
        return

    # 1. 根據多空選擇標頭與顏色 (TG 不支援直接改文字顏色，我們用 Emoji 表達)
    is_bullish = "多頭" in trend
    icon = "🚀" if is_bullish else "📉"
    trend_tag = "【多頭突破】" if is_bullish else "【空頭跌破】"

    # 2. 構建 HTML 格式的訊息內容 (TG 的 HTML 模式很好用)
    message_text = (
        f"<b>{icon} 策略觸發：{trend}</b>\n"
        f"<b>━━━━━━━━━━━━━━</b>\n"
        f"<b>📈 標的：</b> <code>{stock_id}</code>\n"
        f"<b>💰 觸發價：</b> <u>{price}</u>\n"
        f"<b>🎯 關鍵價：</b> {limit_price}\n"
        f"<b>🛑 建議停損：</b> <b>{stop_loss}</b>\n"
        f"<b>━━━━━━━━━━━━━━</b>\n"
        f"<b>📍 產業：</b> {industry}\n"
        f"<b>💡 題材：</b> {themes}\n"
    )

    # 3. 準備按鈕 (K線圖連結)
    clean_symbol = stock_id.split(' ')[0]
    chart_url = f"https://www.fugle.tw/ai/{clean_symbol}"
    
    inline_keyboard = {
        "inline_keyboard": [[
            {"text": "📊 查看即時 K 線", "url": chart_url}
        ]]
    }

    # 4. 發送請求
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML",
        "reply_markup": inline_keyboard
    }

    try:
        response = requests.post(api_url, json=payload)
        if response.status_code == 200:
            print(f"✅ Telegram 訊息已發送: {stock_id}")
        else:
            print(f"❌ TG 發送失敗: {response.text}")
    except Exception as e:
        print(f"❌ TG 連線異常: {e}")

if __name__ == "__main__":
    # 測試執行
    send_tg_alert("2330 台積電", "多頭突破", 615, 610, 602, "半導體", "測試 TG 通知")