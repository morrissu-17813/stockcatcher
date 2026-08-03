import os
import requests as standard_requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import urllib3

# 🛡️ 禁用 SSL 警告 (家用網路測試確認無誤後，建議將 verify=False 移除)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 🛡️ 載入環境變數，堅守不硬編碼憑證的資安原則
load_dotenv()

class Config:
    # ✅ 資安修正：強制改回使用 os.getenv() 從 .env 或系統變數中讀取
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_GROUP_ID = os.getenv("LINE_GROUP_ID", "")

def _build_flex_row(label: str, value: str, color: str = "#334155", weight: str = "regular") -> dict:
    """[輔助函數] 構建 LINE Flex Message 的單列 (Row) 版型"""
    return {
        "type": "box",
        "layout": "baseline",
        "spacing": "sm",
        "contents": [
            {"type": "text", "text": label, "color": "#64748b", "size": "sm", "flex": 2},
            {"type": "text", "text": str(value), "color": color, "weight": weight, "size": "sm", "wrap": True, "flex": 6}
        ]
    }

def send_line_flex_message(sid, name, strategy, lp, pct_str, up_pct, ratio, stop_loss, fut_flag, cb_flag, time_str):
    """[正式推播模組] 發送 LINE Flex Message JSON 卡片"""
    token = Config.LINE_CHANNEL_ACCESS_TOKEN
    target_id = Config.LINE_GROUP_ID

    if not token or not target_id:
        print("❌ [錯誤] LINE 憑證或 Group ID 遺失，請檢查 .env 檔案配置。")
        return

    print(f"🕵️‍♂️ [資訊] 準備發送 Flex Message，目標 ID: {target_id[:5]}***")

    # 🎨 台股語意色彩邏輯：漲紅 (#dc2626)、跌綠 (#16a34a)、平盤灰 (#475569)
    price_color = "#dc2626" if up_pct > 0 else "#16a34a" if up_pct < 0 else "#475569"

    # 構築精美的 Flex Message JSON Payload
    flex_payload = {
        "type": "flex",
        "altText": f"🎫 主力訊號: {sid} {name}",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1e293b",
                "contents": [
                    {"type": "text", "text": "🎫 天機選股 - 權證主力訊號", "color": "#ffffff", "weight": "bold", "size": "sm"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": f"{sid} {name}", "weight": "bold", "size": "xl", "color": "#0f172a"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "sm",
                        "contents": [
                            _build_flex_row("策略", strategy),
                            _build_flex_row("現價", f"{lp} ({pct_str})", color=price_color, weight="bold"),
                            _build_flex_row("量比", f"{ratio}x"),
                            _build_flex_row("防守", stop_loss),
                            _build_flex_row("衍生品", f"股期 {fut_flag} | 可轉債 {cb_flag}")
                        ]
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"觸發時間: {time_str}", "size": "xs", "color": "#94a3b8", "align": "end"}
                ]
            }
        }
    }

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    payload = {
        "to": target_id,
        "messages": [flex_payload]
    }

    try:
        # ⚠️ 在沒有企業防火牆的環境下，建議將 verify=False 移除以確保安全
        res = standard_requests.post(url, headers=headers, json=payload, timeout=5, verify=False)
        
        if res.status_code == 200:
            print("✅ [LINE] Flex Message 推播成功！請查看你的 LINE 群組。")
        else:
            print(f"⚠️ [LINE] 推播失敗 (HTTP {res.status_code}): {res.text}")
            
    except Exception as e:
        print(f"❌ [LINE] 發送異常: {e}")

if __name__ == "__main__":
    # 模擬一次盤中觸發的真實數據
    now_tw_str = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%H:%M:%S')
    send_line_flex_message(
        sid="2330", name="台積電", strategy="🔥 策略二：3K突破 + 量能異常",
        lp=1050.0, pct_str="+2.43%", up_pct=2.43, ratio=2.5, stop_loss=1020.0,
        fut_flag="✅", cb_flag="❌", time_str=now_tw_str
    )
