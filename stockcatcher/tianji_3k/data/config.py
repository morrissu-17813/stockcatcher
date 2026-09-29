from pathlib import Path
import os
from dotenv import load_dotenv

def find_project_env():
    here=Path(__file__).resolve()
    candidates=[here.parents[2]/'.env',here.parents[3]/'stockcatcher'/'.env',here.parents[4]/'.env']
    for p in candidates:
        if p.exists(): return p
    return candidates[0]
ENV_PATH=find_project_env(); load_dotenv(ENV_PATH)
FUGLE_API_KEY=os.getenv('FUGLE_API_KEY','').strip(); FINMIND_TOKEN=os.getenv('FINMIND_TOKEN','').strip(); TELEGRAM_BOT_TOKEN=(os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN') or '').strip(); TELEGRAM_CHAT_ID=os.getenv('TELEGRAM_CHAT_ID','').strip()
MIS_BATCH_SIZE=int(os.getenv('TIANJI_MIS_BATCH_SIZE','25')); MIS_INTERVAL_SECONDS=int(os.getenv('TIANJI_MIS_INTERVAL_SECONDS','20')); HTTP_TIMEOUT=int(os.getenv('TIANJI_HTTP_TIMEOUT','15')); VOLUME_THRESHOLD_LOTS=float(os.getenv('TIANJI_STAGE0_VOLUME_THRESHOLD','1000')); RADAR_MIN_YESTERDAY_VOLUME_LOTS=float(os.getenv('TIANJI_RADAR_MIN_YESTERDAY_VOLUME_LOTS','500')); BREAKOUT_BUFFER_PCT=float(os.getenv('TIANJI_BREAKOUT_BUFFER_PCT','0.3'))
