import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from FinMind.data import DataLoader

# ==========================================
# 參數設定區
# ==========================================
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiRVNCMTc4MTMiLCJlbWFpbCI6Im0yOTk0MDUwOUBob3RtYWlsLmNvbSJ9.iGsA_PLkanve2aATgXU-RD2i7RKOHSLzMEmASMBOcDE"          # 若有 FinMind Token 請貼於引號內，留空亦可正常運作
MAX_WORKERS = 10            # 平行處理線程數 (建議 8 ~ 12)
MIN_5VMA_LOTS = 1000        # 流動性門檻 (5日均量 >= 1000張)


def fetch_and_evaluate_3k(stock_id: str, dl: DataLoader, start_date: str) -> dict:
    """
    單一股票 3K 法邏輯驗證
    """
    try:
        df = dl.taiwan_stock_daily(stock_id=stock_id, start_date=start_date)
        if df is None or len(df) < 60:
            return None

        df['close'] = df['close'].astype(float)
        df['max'] = df['max'].astype(float)
        df['Trading_Volume'] = df['Trading_Volume'].astype(float)

        df['20MA'] = df['close'].rolling(window=20).mean()
        df['60MA'] = df['close'].rolling(window=60).mean()
        df['5VMA'] = df['Trading_Volume'].rolling(window=5).mean() / 1000.0

        k_0 = df.iloc[-1]
        k_1 = df.iloc[-2]
        k_2 = df.iloc[-3]

        # 3K 突破條件驗證
        if (k_0['close'] > k_0['20MA'] and 
            k_0['close'] > k_0['60MA'] and 
            k_0['close'] > k_1['max'] and 
            k_0['close'] > k_2['max'] and 
            k_0['5VMA'] >= MIN_5VMA_LOTS):
            
            return {
                "股票代碼": stock_id,
                "前日收盤價": k_0['close'],
                "20MA": round(k_0['20MA'], 2),
                "60MA": round(k_0['60MA'], 2),
                "5日均量(張)": int(k_0['5VMA'])
            }
    except Exception:
        pass
    return None


def run_timed_screener():
    """
    帶有精確計時功能的全市場選股進入點
    """
    dl = DataLoader()
    
    # 修復處：安全登入邏輯 (傳遞位置引數)
    if FINMIND_TOKEN and FINMIND_TOKEN.strip():
        try:
            dl.login_by_token(FINMIND_TOKEN)
        except Exception as e:
            print(f"⚠️ Token 登入失敗，將以免費無 Token 模式繼續執行: {e}")

    # 紀錄開始時間
    start_time = time.time()
    print(f"⏰ 腳本啟動時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 取得全市場股票清單
    info_df = dl.taiwan_stock_info()
    stock_list = info_df[
        (info_df['industry_category'].notnull()) & 
        (info_df['industry_category'] != '') &
        (~info_df['stock_id'].str.contains(r'[A-Za-z]', regex=True)) & 
        (info_df['stock_id'].str.len() == 4)
    ]['stock_id'].unique().tolist()

    total_stocks = len(stock_list)
    print(f"📦 已取得全市場標的：共 {total_stocks} 檔")

    start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    selected_stocks = []
    completed = 0

    # 2. 多線程加速掃瞄
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(fetch_and_evaluate_3k, sid, dl, start_date): sid 
            for sid in stock_list
        }

        for future in as_completed(future_map):
            completed += 1
            res = future.result()
            if res:
                selected_stocks.append(res)
            
            # 每完成 200 檔顯示一次即時耗時與進度
            if completed % 200 == 0 or completed == total_stocks:
                elapsed = time.time() - start_time
                print(f"⏳ 進度: {completed}/{total_stocks} ({completed/total_stocks*100:.1f}%) | 已耗時: {elapsed:.1f} 秒")

    # 3. 計算總耗時與結果輸出
    total_elapsed = time.time() - start_time
    print("\n==================================================")
    print(f"✅ 掃瞄完成！總共耗時：{total_elapsed:.2f} 秒 ({total_elapsed/60:.2f} 分鐘)")
    print(f"🎯 符合【3K法選股】標的數量：{len(selected_stocks)} 檔")
    print("==================================================")

    result_df = pd.DataFrame(selected_stocks)
    if not result_df.empty:
        result_df.to_csv("watchlist_3k.csv", index=False, encoding="utf-8-sig")
        print("💾 結果已寫入 watchlist_3k.csv")


if __name__ == "__main__":
    run_timed_screener()