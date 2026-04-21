import os
from dotenv import load_dotenv
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, 
    PushMessageRequest, FlexMessage, FlexContainer
)

# 1. 初始化設定
load_dotenv()
access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
user_id = os.getenv("LINE_USER_ID")

def send_3k_alert(stock_id, trend, price, limit_price, stop_loss, industry, themes):
    """
    發送包含完整資訊與 K 線連結的 Line Flex Message
    """
    # 確保 Token 存在
    if not access_token or not user_id:
        print("❌ 錯誤：找不到 Line Token 或 User ID，請檢查 .env 檔案")
        return

    configuration = Configuration(access_token=access_token)
    
    # 提取股票代號以生成 K 線連結 (例如從 "2330 台積電" 提取 "2330")
    clean_symbol = stock_id.split(' ')[0]
    chart_url = f"https://www.fugle.tw/ai/{clean_symbol}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        # 根據多空方向決定視覺顏色
        is_bullish = "多頭" in trend
        main_color = "#E63946" if is_bullish else "#2A9D8F"  # 多頭紅，空頭綠
        icon = "🚀" if is_bullish else "📉"
        
        # 建立 Flex Message 結構
        flex_contents = {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"{icon} {trend}", "color": "#FFFFFF", "weight": "bold", "size": "lg"}
                ],
                "backgroundColor": main_color
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    # 股票代號與名稱
                    {"type": "text", "text": stock_id, "weight": "bold", "size": "xl", "margin": "md"},
                    {"type": "separator", "margin": "lg"},
                    
                    # 價格資訊區 (觸發價、關鍵價、停損價)
                    {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [
                        {"type": "box", "layout": "horizontal", "contents": [
                            {"type": "text", "text": "觸發價格", "color": "#888888", "size": "sm"},
                            {"type": "text", "text": str(price), "align": "end", "weight": "bold", "color": main_color}
                        ]},
                        {"type": "box", "layout": "horizontal", "contents": [
                            {"type": "text", "text": "關鍵價位", "color": "#888888", "size": "sm"},
                            {"type": "text", "text": str(limit_price), "align": "end", "size": "sm"}
                        ]},
                        {"type": "box", "layout": "horizontal", "contents": [
                            {"type": "text", "text": "建議停損", "color": "#888888", "size": "sm"},
                            {"type": "text", "text": str(stop_loss), "align": "end", "size": "sm", "color": "#FF0000"}
                        ]}
                    ]},
                    {"type": "separator", "margin": "lg"},
                    
                    # 產業與題材區
                    {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "xs", "contents": [
                        {"type": "text", "text": f"📍 產業：{industry}", "size": "xs", "color": "#555555"},
                        {"type": "text", "text": f"💡 題材：{themes}", "size": "xs", "color": "#555555", "wrap": True}
                    ]}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": main_color,
                        "action": {
                            "type": "uri",
                            "label": "📊 查看即時 K 線",
                            "uri": chart_url
                        }
                    },
                    {"type": "text", "text": "⚠️ 策略僅供參考，投資請謹慎判斷", "size": "xxs", "color": "#aaaaaa", "align": "center"}
                ]
            }
        }

        # 封裝訊息
        flex_message = FlexMessage(
            alt_text=f"【{trend}】{stock_id} 觸發！",
            contents=FlexContainer.from_dict(flex_contents)
        )
        
        # 執行發送
        try:
            line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[flex_message]))
            return True
        except Exception as e:
            print(f"❌ Line 推播發送失敗: {e}")
            return False

# 這裡可以保留一段測試用的代碼
if __name__ == "__main__":
    # 測試執行
    send_3k_alert(
        stock_id="2330 台積電",
        trend="盤中 3K 多頭突破",
        price=615.0,
        limit_price=610.0,
        stop_loss=602.0,
        industry="半導體 / 晶圓代工",
        themes="AI 伺服器需求暴增、先進製程訂單滿載"
    )