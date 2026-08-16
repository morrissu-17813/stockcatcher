"""
finlab_full_crawler.py
角色：程式小幫手-蘇蘇 (全端軟體工程師)
目的：全量掃描 FinLab 概念股目錄，非同步造訪所有子頁面，直接駭入 SvelteKit 
      底層狀態機進行高精度資料萃取，最終產出 JSON 主檔並同步至 Supabase 資料庫。
技術棧：Python (asyncio, httpx, re, json, logging, supabase)
"""

import asyncio
import httpx
import re
import json
import logging
import os
from supabase import create_client, Client
from typing import List, Dict, Any, Optional

# ==========================================
# 1. 系統設定與日誌初始化
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
BASE_THEME_URL = "https://finlab.finance/stocks/themes"

# ==========================================
# 2. 強固型網路請求引擎
# ==========================================
async def fetch_html_async(client: httpx.AsyncClient, url: str, max_retries: int = 3) -> Optional[str]:
    """非同步抓取網頁，具備偽裝與指數退避重試機制"""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.get(url, headers=headers, timeout=20.0)
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(f"HTTP Status: {response.status_code}", request=response.request, response=response)
            response.raise_for_status()
            return response.text
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            wait_time = attempt * 2
            if attempt == max_retries:
                logger.error(f"❌ 請求最終失敗 (URL: {url}), 錯誤: {e}")
                return None
            logger.warning(f"⚠️ 請求異常 (嘗試 {attempt}/{max_retries})，等待 {wait_time} 秒後重試... ({url})")
            await asyncio.sleep(wait_time)
            
    return None

# ==========================================
# 3. 目錄解析與狀態機萃取引擎
# ==========================================
def extract_all_theme_slugs(html_content: str) -> List[str]:
    """從 FinLab 首頁萃取所有子主題的路由縮寫 (Slug)"""
    pattern = r'href=["\'](?:https://finlab\.finance)?/stocks/themes/([^/"\']+)["\']'
    slugs = re.findall(pattern, html_content)
    return list(set([s for s in slugs if s.strip()]))

def extract_finlab_theme_data(html_content: str, slug: str) -> Dict[str, Any]:
    """深度解譯 SvelteKit 狀態機，剝離概念名稱與成分股"""
    result = {
        "concept": "未知名稱",
        "slug": slug,
        "stocks": []
    }

    theme_match = re.search(r'theme:\{slug:"[^"]+",name:"([^"]+)"', html_content)
    if theme_match:
        result["concept"] = theme_match.group(1)

    rows_match = re.search(r'rows:\[(.*?)\],(?:[a-zA-Z0-9_]+):', html_content, re.DOTALL)
    if not rows_match:
        return result

    rows_raw = rows_match.group(1)
    stock_pattern = r'symbol:"(\d{4,5})",name:"([^"]+)"'
    for match in re.finditer(stock_pattern, rows_raw):
        result["stocks"].append({
            "symbol": match.group(1),
            "name": match.group(2)
        })

    unique_stocks = {s["symbol"]: s for s in result["stocks"]}.values()
    result["stocks"] = list(unique_stocks)

    return result

# ==========================================
# 4. 非同步任務控制器
# ==========================================
async def fetch_single_theme_task(
    client: httpx.AsyncClient, 
    slug: str, 
    semaphore: asyncio.Semaphore
) -> Optional[Dict[str, Any]]:
    """受信號量保護的單一主題抓取任務"""
    async with semaphore:
        await asyncio.sleep(0.5)
        
        target_url = f"{BASE_THEME_URL}/{slug}"
        html = await fetch_html_async(client, target_url)
        
        if not html:
            logger.warning(f"⚠️ 略過主題 [{slug}]：無法取得網頁源碼。")
            return None
            
        data = extract_finlab_theme_data(html, slug)
        stock_count = len(data["stocks"])
        
        if stock_count > 0:
            logger.info(f"✅ 完成 [{data['concept']}] - 收錄 {stock_count} 檔成分股")
            return data
        else:
            logger.warning(f"⚠️ 警告 [{slug}] - 抓取成功但未解析出任何成分股。")
            return None

# ==========================================
# 5. Supabase 資料庫同步引擎
# ==========================================
def sync_to_supabase(themes_data: List[Dict[str, Any]]):
    """將概念股清單安全地 Upsert 至 Supabase 資料庫"""
    url: str = "https://iatlchzzjkjaetorvvil.supabase.co"    
    key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlhdGxjaHp6amtqYWV0b3J2dmlsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NjAzMDQzMywiZXhwIjoyMTAxNjA2NDMzfQ.FckTSOyIo_QCocrgfaGd9mHV2wXRJxSeC5955936hSQ"
    
    if not url or not key:
        logger.error("❌ 找不到 Supabase 憑證！請確認 GitHub Secrets 或本機環境變數已正確設定。")
        return

    logger.info("🔗 連線至 Supabase 資料庫...")
    supabase: Client = create_client(url, key)
    
    total_inserted = 0
    for theme in themes_data:
        concept_name = theme["concept"]
        slug = theme["slug"]
        
        # 1. 寫入主題表 (Upsert：有則更新，無則新增)
        theme_resp = supabase.table("themes").upsert(
            {"slug": slug, "concept_name": concept_name}, 
            on_conflict="slug"
        ).execute()
        
        theme_id = theme_resp.data[0]["id"]
        
        # 2. 準備該主題的成分股清單
        stock_inserts = [
            {"theme_id": theme_id, "symbol": s["symbol"], "stock_name": s["name"]}
            for s in theme["stocks"]
        ]
        
        # 3. 確保資料最新：先刪除舊關聯，再寫入新關聯
        supabase.table("theme_stocks").delete().eq("theme_id", theme_id).execute()
        if stock_inserts:
            supabase.table("theme_stocks").insert(stock_inserts).execute()
            total_inserted += len(stock_inserts)

    logger.info(f"✅ Supabase 同步完成！共更新 {len(themes_data)} 個主題，寫入 {total_inserted} 筆個股關聯。")

# ==========================================
# 6. 主排程器
# ==========================================
async def main():
    logger.info("🚀 FinLab 全市場概念股收集引擎啟動...")
    
    limits = httpx.Limits(max_connections=5, max_keepalive_connections=3)
    
    async with httpx.AsyncClient(limits=limits, trust_env=True, verify=False) as client:
        logger.info(f"正在取得概念股首頁目錄: {BASE_THEME_URL}")
        index_html = await fetch_html_async(client, BASE_THEME_URL)
        if not index_html:
            logger.critical("無法取得目錄頁，程式終止。")
            return
            
        slugs = extract_all_theme_slugs(index_html)
        logger.info(f"✨ 成功解析出總計 {len(slugs)} 個主題路由！")
        
        if not slugs:
            return
            
        semaphore = asyncio.Semaphore(3)
        tasks = [fetch_single_theme_task(client, slug, semaphore) for slug in slugs]
        
        logger.info("準備發動非同步萃取，預計需時 1~2 分鐘...")
        results = await asyncio.gather(*tasks)
        
        valid_results = [r for r in results if r is not None and r["stocks"]]
        total_relations = sum(len(r["stocks"]) for r in valid_results)
        
        logger.info(f"🎉 採集完成！成功收錄 {len(valid_results)} 個族群，共計建立 {total_relations} 筆個股關聯。")
        
        # 匯出 JSON 主檔作為備份
        if valid_results:
            output_filename = "finlab_themes_master.json"
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(valid_results, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 完整 JSON 主檔已成功儲存至：{output_filename}")
            
            # 同步至資料庫
            logger.info("☁️ 開始將資料同步寫入 Supabase...")
            sync_to_supabase(valid_results)

if __name__ == "__main__":
    asyncio.run(main())