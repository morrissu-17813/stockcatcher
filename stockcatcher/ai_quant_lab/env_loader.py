"""Load the user's existing stockcatcher/.env without exposing secrets."""
from __future__ import annotations
import os
from pathlib import Path
HERE=Path(__file__).resolve().parent
# Expected repo layout: repo/stockcatcher/.env and repo/ai_quant_lab/.
CANDIDATES=(HERE.parent/"stockcatcher"/"stockcatcher"/".env", HERE.parent/"stockcatcher"/".env", HERE.parent/".env", HERE.parent.parent/"stockcatcher"/"stockcatcher"/".env", HERE.parent.parent/"stockcatcher"/".env", HERE/".env")

def load_lab_env():
    loaded_from=None
    for path in CANDIDATES:
        if not path.is_file(): continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line=raw.strip()
            if not line or line.startswith("#"): continue
            if line.startswith("export "): line=line[7:].lstrip()
            if "=" not in line: continue
            key,value=line.split("=",1); key=key.strip(); value=value.strip()
            if not key or not key.replace("_","").isalnum(): continue
            if len(value)>=2 and value[0]==value[-1] and value[0] in ("'",'"'): value=value[1:-1]
            os.environ.setdefault(key,value)
        loaded_from=str(path); break
    has=lambda *names:any(os.getenv(n) for n in names)
    return {"loaded":loaded_from is not None,"path":loaded_from,
      "supabase_configured":has("SUPABASE_URL") and has("SUPABASE_SERVICE_ROLE_KEY"),
      "fugle_configured":has("FUGLE_API_KEY","FUGLE_KEY","FUGLE_API_TOKEN"),
      "finmind_configured":has("FINMIND_TOKEN","FINMIND_API_TOKEN","FINMIND_TOKEN_ID"),
      "telegram_configured":has("TELEGRAM_BOT_TOKEN","TELEGRAM_TOKEN") and has("TELEGRAM_CHAT_ID")}
