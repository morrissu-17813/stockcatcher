#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ToAlpha MCP batch downloader for Tianji 2TON (24 Taiwan stocks).
Requires Python 3.10+ and requests: pip install requests
Run: python toalpha_2ton_batch.py --days 1000
Optional API key: python toalpha_2ton_batch.py --days 1000 --api-key YOUR_KEY
"""
import argparse, csv, json, re, time
from pathlib import Path
import requests

ENDPOINT = "https://toalpha.tw/mcp"
OUT = Path("toalpha_2ton_data")
OUT.mkdir(exist_ok=True)
STOCKS = [
("1301","台塑"),("2241","艾姆勒"),("2305","全友"),("2340","台亞"),
("2466","冠西電"),("3026","禾伸堂"),("3147","大綜"),("3236","千如"),
("3564","其陽"),("3624","光頡"),("3661","世芯-KY"),("3693","營邦"),
("4720","德淵"),("4760","勤凱"),("5243","乙盛-KY"),("6122","擎邦"),
("6152","百一"),("6174","安碁"),("6505","台塑化"),("6672","騰輝電子-KY"),
("8042","金山電"),("8289","泰藝"),("2426","鼎元"),("2484","希華")]

class MCP:
    def __init__(self, key=None):
        self.s=requests.Session()
        self.s.headers.update({"Content-Type":"application/json",
          "Accept":"application/json, text/event-stream",
          "User-Agent":"Tianji2TON-ToAlphaClient/1.0"})
        if key: self.s.headers["Authorization"]="Bearer "+key
        self.sid=None; self.i=1
    def rpc(self, method, params=None, notification=False):
        body={"jsonrpc":"2.0","method":method}
        if not notification: body["id"]=self.i; self.i+=1
        if params is not None: body["params"]=params
        h={"Mcp-Session-Id":self.sid} if self.sid else {}
        r=self.s.post(ENDPOINT,json=body,headers=h,timeout=60); r.raise_for_status()
        if r.headers.get("Mcp-Session-Id"): self.sid=r.headers["Mcp-Session-Id"]
        if notification or r.status_code==202 or not r.text.strip(): return None
        if "json" in r.headers.get("content-type",""):
            obj=r.json()
        else:
            obj=None
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    raw=line[5:].strip()
                    if raw and raw!="[DONE]":
                        obj=json.loads(raw); break
        if obj is None: raise RuntimeError("Unexpected MCP response: "+r.text[:1000])
        if "error" in obj: raise RuntimeError(str(obj["error"]))
        return obj.get("result",obj)
    def connect(self):
        x=self.rpc("initialize",{"protocolVersion":"2025-03-26","capabilities":{},
          "clientInfo":{"name":"tianji-2ton-toalpha","version":"1.0"}})
        self.rpc("notifications/initialized",notification=True)
        return x
    def tools(self):
        x=self.rpc("tools/list",{})
        return x.get("tools",[]) if isinstance(x,dict) else []
    def call(self,name,args): return self.rpc("tools/call",{"name":name,"arguments":args})

def unwrap(x):
    if isinstance(x,dict) and isinstance(x.get("content"),list):
        texts=[v.get("text","") for v in x["content"] if isinstance(v,dict) and v.get("type")=="text"]
        if len(texts)==1:
            try: return json.loads(texts[0])
            except Exception: return {"text":texts[0],"isError":x.get("isError",False)}
        if texts: return {"content":texts,"isError":x.get("isError",False)}
    return x

def find_tool(tools, pattern):
    return next((t for t in tools if re.search(pattern,t.get("name",""),re.I)),None)

def normalize(data,code,name):
    if isinstance(data,list): rows=data
    elif isinstance(data,dict):
        rows=next((data[k] for k in ("rows","data","history","prices","items","results")
                   if isinstance(data.get(k),list)),None)
        if rows is None:
            rows=next((v for v in data.values() if isinstance(v,list) and v and isinstance(v[0],dict)),[])
    else: return []
    out=[]
    for row in rows:
        if not isinstance(row,dict): continue
        d={str(k).lower().replace("_",""):v for k,v in row.items()}
        def get(*ks):
            for k in ks:
                if k.lower().replace("_","") in d: return d[k.lower().replace("_","")]
        dt=get("date","trade_date","tradedate","day","日期")
        if dt is None: continue
        out.append({"date":dt,"code":code,"name":name,
          "open":get("open","開盤","開"),"high":get("high","最高","高"),
          "low":get("low","最低","低"),"close":get("close","收盤","收"),
          "volume":get("volume","volume_lots","trading_volume","成交張數","成交量"),
          "amount":get("amount","turnover","成交金額"),
          "transactions":get("transactions","trades","成交筆數"),
          "raw_row":json.dumps(row,ensure_ascii=False)})
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--days",type=int,default=1000)
    ap.add_argument("--api-key",default=None)
    ap.add_argument("--pause",type=float,default=.25)
    a=ap.parse_args()
    if not 1<=a.days<=1000: raise SystemExit("--days must be 1..1000")
    c=MCP(a.api_key)
    print("Connecting to ToAlpha MCP...",flush=True)
    init=c.connect()
    (OUT/"initialize.json").write_text(json.dumps(init,ensure_ascii=False,indent=2),encoding="utf-8")
    tools=c.tools()
    (OUT/"tools.json").write_text(json.dumps(tools,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Tools:",", ".join(t.get("name","") for t in tools),flush=True)
    st=find_tool(tools,r"data_status|status")
    hist=find_tool(tools,r"price_history|pricehistory|historical.*price|daily.*price")
    if not hist: raise SystemExit("price_history tool not identified; inspect toalpha_2ton_data/tools.json")
    print("History tool schema:",json.dumps(hist.get("inputSchema",{}),ensure_ascii=False),flush=True)
    if st:
        try:
            (OUT/"data_status.json").write_text(json.dumps(unwrap(c.call(st["name"],{})),ensure_ascii=False,indent=2),encoding="utf-8")
        except Exception as e: print("data_status failed:",e,flush=True)
    props=hist.get("inputSchema",{}).get("properties",{})
    sk=next((k for k in props if k.lower() in ("stock_id","stockid","code","ticker")),None)
    dk=next((k for k in props if k.lower()=="days"),None)
    ak=next((k for k in props if k.lower()=="adjusted"),None)
    if not sk or not dk: raise SystemExit("Unrecognized price_history schema: "+json.dumps(props,ensure_ascii=False))
    raw={}; normalized=[]
    for code,name in STOCKS:
        args={sk:code,dk:a.days}
        if ak: args[ak]=False
        print(f"[{code} {name}] requesting {a.days} days",flush=True)
        try:
            result=unwrap(c.call(hist["name"],args))
            raw[code]={"name":name,"arguments":args,"result":result}
            rows=normalize(result,code,name); normalized.extend(rows)
            print("  normalized rows:",len(rows),flush=True)
        except Exception as e:
            raw[code]={"name":name,"arguments":args,"error":str(e)}
            print("  ERROR:",e,flush=True)
        time.sleep(a.pause)
    (OUT/"price_history_raw.json").write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding="utf-8")
    if normalized:
        cols=["date","code","name","open","high","low","close","volume","amount","transactions","raw_row"]
        with (OUT/"price_history.csv").open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(normalized)
    summary={"endpoint":ENDPOINT,"stocks_requested":len(STOCKS),
      "stocks_with_response":sum("result" in v for v in raw.values()),
      "stocks_with_normalized_rows":len({r["code"] for r in normalized}),
      "normalized_rows":len(normalized),"days_requested":a.days,
      "history_tool":hist["name"],
      "note":"Review raw response metadata and docs to confirm volume unit before calculating 2TON levels."}
    (OUT/"manifest.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    print("Output folder:",OUT.resolve(),flush=True)

if __name__=="__main__": main()
