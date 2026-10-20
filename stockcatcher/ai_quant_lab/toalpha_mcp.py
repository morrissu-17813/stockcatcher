"""Small Streamable HTTP MCP client for ToAlpha Taiwan-stock research tools."""
from __future__ import annotations
import json, urllib.request, urllib.error, uuid, threading
ENDPOINT='https://toalpha.tw/mcp'
_lock=threading.RLock(); _session_id=None; _initialized=False; _tools_cache=None

def _decode_response(body, content_type):
    text=body.decode('utf-8','replace').strip()
    if not text: return {}
    if 'text/event-stream' in (content_type or '') or text.startswith('event:') or text.startswith('data:'):
        out=[]
        for line in text.splitlines():
            if line.startswith('data:'):
                try: out.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError: pass
        return out[-1] if out else {'raw':text[:4000]}
    try: return json.loads(text)
    except json.JSONDecodeError: return {'raw':text[:4000]}

def _post(payload, notification=False):
    global _session_id
    headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream','User-Agent':'AIQuantLab/1.3 MCP Client'}
    if _session_id: headers['Mcp-Session-Id']=_session_id
    req=urllib.request.Request(ENDPOINT,data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers=headers,method='POST')
    try:
        with urllib.request.urlopen(req,timeout=18) as res:
            sid=res.headers.get('Mcp-Session-Id')
            if sid: _session_id=sid
            body=res.read(); ctype=res.headers.get('Content-Type','')
    except urllib.error.HTTPError as exc:
        body=exc.read().decode('utf-8','replace')[:1000]
        raise RuntimeError(f'ToAlpha MCP HTTP {exc.code}: {body}') from exc
    except (urllib.error.URLError,TimeoutError) as exc: raise RuntimeError(f'ToAlpha MCP 連線失敗：{exc}') from exc
    if notification: return {}
    result=_decode_response(body,ctype)
    if isinstance(result,dict) and result.get('error'): raise RuntimeError(f"MCP error: {result['error']}")
    if isinstance(result,dict) and 'result' in result: return result['result']
    return result

def _initialize():
    global _initialized
    if _initialized: return
    result=_post({'jsonrpc':'2.0','id':str(uuid.uuid4()),'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'Tianji AI Quant Lab','version':'1.3'}}})
    _post({'jsonrpc':'2.0','method':'notifications/initialized','params':{}},notification=True)
    _initialized=True

def list_tools(force=False):
    global _tools_cache
    with _lock:
        if _tools_cache is not None and not force: return _tools_cache
        _initialize(); result=_post({'jsonrpc':'2.0','id':str(uuid.uuid4()),'method':'tools/list','params':{}})
        tools=result.get('tools',[]) if isinstance(result,dict) else []
        _tools_cache=[{'name':t.get('name'),'title':t.get('title') or t.get('name'),'description':t.get('description',''),'inputSchema':t.get('inputSchema',{'type':'object','properties':{}})} for t in tools if isinstance(t,dict) and t.get('name')]
        return _tools_cache

def call_tool(name, arguments=None):
    with _lock:
        allowed={t['name'] for t in list_tools()}
        if name not in allowed: raise ValueError(f'不允許呼叫未列出的 MCP 工具：{name}')
        result=_post({'jsonrpc':'2.0','id':str(uuid.uuid4()),'method':'tools/call','params':{'name':name,'arguments':arguments or {}}})
        return result
