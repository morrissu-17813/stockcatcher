from line_test import send_3k_alert

def run_test():
    print("🧪 正在發送『全資訊豪華版』測試卡片...")
    
    # 模擬資料：假設台積電突破
    send_3k_alert(
        stock_id="2330 台積電",
        trend="盤中 3K 多頭突破",
        price=612.0,
        limit_price=605.0,
        stop_loss=598.0,
        industry="半導體 / 代工",
        themes="AI 需求強勁、先進製程 2nm 領先、外資買超"
    )

    # 模擬資料：假設長榮跌破
    send_3k_alert(
        stock_id="2603 長榮",
        trend="盤中 3K 空頭跌破",
        price=152.5,
        limit_price=155.0,
        stop_loss=158.0,
        industry="航運 / 貨櫃",
        themes="運價指數回落、紅海危機緩解、供給過剩隱憂"
    )

if __name__ == "__main__":
    run_test()