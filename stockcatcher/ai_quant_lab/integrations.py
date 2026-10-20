"""Environment discovery and safe integrations for the isolated AI Quant Lab.
Secrets stay in the backend; never expose values through API responses or logs.
"""
from __future__ import annotations
import os, json, urllib.request, urllib.error
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

def load_env_files() -> list[str]:
    """Load .env files without overriding variables already supplied by the process."""
    candidates = [ROOT / '.env', ROOT.parent / '.env', ROOT.parent.parent / '.env',
                  ROOT.parent / 'stockcatcher' / '.env', ROOT.parent.parent / 'stockcatcher' / '.env',
                  ROOT.parent.parent / 'stockcatcher' / 'stockcatcher' / '.env',
                  Path.cwd() / '.env', Path.cwd().parent / '.env', Path.cwd().parent / 'stockcatcher' / '.env']
    loaded=[]
    seen=set()
    for path in candidates:
        try: path=path.resolve()
        except OSError: continue
        if path in seen or not path.is_file(): continue
        seen.add(path)
        try:
            for raw in path.read_text(encoding='utf-8-sig').splitlines():
                line=raw.strip()
                if not line or line.startswith('#'): continue
                if line.startswith('export '): line=line[7:].strip()
                if '=' not in line: continue
                key,value=line.split('=',1); key=key.strip(); value=value.strip()
                if not key or not key.replace('_','').isalnum(): continue
                if len(value)>=2 and value[0]==value[-1] and value[0] in ('"', "'"): value=value[1:-1]
                if key not in os.environ: os.environ[key]=value
            loaded.append(str(path))
        except (OSError, UnicodeError): continue
    return loaded

load_env_files()

def first_env(*keys: str) -> str:
    for key in keys:
        value=os.getenv(key,'').strip()
        if value: return value
    return ''

def integration_status() -> dict[str, Any]:
    return {
      'env_files_loaded': len(load_env_files()),
      'fugle_configured': bool(first_env('FUGLE_API_KEY','FUGLE_KEY','FUGLE_TOKEN')),
      'finmind_configured': bool(first_env('FINMIND_TOKEN','FINMIND_API_TOKEN','FINMIND_API_KEY')),
      'supabase_configured': bool(first_env('SUPABASE_URL') and first_env('SUPABASE_SERVICE_ROLE_KEY','SUPABASE_SECRET_KEY','SUPABASE_KEY')),
      'telegram_configured': bool(first_env('TELEGRAM_BOT_TOKEN','TELEGRAM_TOKEN') and first_env('TELEGRAM_CHAT_ID','TELEGRAM_CHATID')),
      'broker_connected': False, 'live_orders_enabled': False,
    }

class TelegramNotifier:
    def __init__(self):
        self.token=first_env('TELEGRAM_BOT_TOKEN','TELEGRAM_TOKEN')
        self.chat_id=first_env('TELEGRAM_CHAT_ID','TELEGRAM_CHATID')
    @property
    def configured(self): return bool(self.token and self.chat_id)
    def send(self, text: str) -> dict[str, Any]:
        if not self.configured: return {'sent':False,'reason':'not_configured'}
        payload=json.dumps({'chat_id':self.chat_id,'text':text[:3900],'disable_web_page_preview':True}).encode()
        req=urllib.request.Request(f'https://api.telegram.org/bot{self.token}/sendMessage',data=payload,headers={'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=8) as r: result=json.loads(r.read().decode())
            return {'sent':bool(result.get('ok')),'reason':None if result.get('ok') else 'provider_rejected'}
        except Exception as exc:
            return {'sent':False,'reason':type(exc).__name__}
