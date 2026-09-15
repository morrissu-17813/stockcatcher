from pathlib import Path
import os
from dotenv import load_dotenv

# tianji_3k/data/config.py -> stockcatcher/.env
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

FUGLE_API_KEY = os.getenv("FUGLE_API_KEY", "")
MIS_API_KEY = os.getenv("MIS_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
