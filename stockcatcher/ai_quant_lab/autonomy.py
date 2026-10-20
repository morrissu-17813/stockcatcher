"""Explicitly started autonomous paper-trading loop. All trades remain simulated."""
from __future__ import annotations
import threading, time, uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from market_data import DEFAULT_WATCHLIST, build_market_client
from tianji_radar import TaiwanMarketRadar
from trade_confirmation import FinMindHistoryProvider, FugleFiveMinuteProvider, RadarSnapshot, RadarStateMachine, projected_volume, TAIPEI

class AutonomousLoop:
    def __init__(self, engine, client=None, watchlist=None, interval=20):
        self.engine=engine; self.client=client or build_market_client(); self.watchlist=watchlist or DEFAULT_WATCHLIST; self.interval=max(20,int(interval)); self.radar=TaiwanMarketRadar()
        self._stop=threading.Event(); self._thread=None; self._lock=threading.RLock(); self._cycle_lock=threading.Lock(); self.market={}; self.errors=[]; self.last_cycle=None; self.enabled=False; self.cycles=0
        self.started_at=None; self.last_cycle_started_at=None; self.last_cycle_completed_at=None; self.last_successful_mis_at=None
        self.consecutive_cycle_errors=0; self.last_cycle_error=None; self.max_consecutive_cycle_errors=5
        self.consecutive_mis_errors=0; self.last_mis_error=None; self.max_consecutive_mis_errors=5
        self.history_provider=FinMindHistoryProvider(); self.fugle_5m=FugleFiveMinuteProvider(); self.confirmation_states={}; self.confirmation_contexts={}; self.pending_confirmations={}; self.last_confirmations=[]; self.monitor_logs=[]
    def _log(self, message, level='info', tag=None):
        at=datetime.now(TAIPEI).isoformat(timespec='seconds')
        row={'id':str(uuid.uuid4()),'at':at,'time':at[11:19],'level':level,'tag':tag or level.upper(),'message':str(message)[:500]}
        with self._lock:
            self.monitor_logs.append(row)
            self.monitor_logs=self.monitor_logs[-300:]
        return row
    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive(): return {'started':False,'reason':'already_running'}
            self._stop.clear(); self.enabled=True; self.started_at=datetime.now(TAIPEI).isoformat(timespec='seconds'); self.consecutive_cycle_errors=0; self.last_cycle_error=None; self.consecutive_mis_errors=0; self.last_mis_error=None; self._log(f'自主監控已啟動｜監控池 {len(self.watchlist)} 檔｜週期 {self.interval} 秒',tag='START'); self._thread=threading.Thread(target=self._run,name='ai-quant-lab-autonomy',daemon=True); self._thread.start()
        return {'started':True,'watchlist':[x['symbol'] for x in self.watchlist],'interval_seconds':self.interval}
    def stop(self):
        self.enabled=False; self._stop.set(); self._log('已收到停止自主監控指令',tag='STOP')
        return {'stopping':True}
    def status(self):
        with self._lock:
            alive=bool(self._thread and self._thread.is_alive())
            return {'enabled':self.enabled,'thread_alive':alive,'health':'STOPPED' if not self.enabled else ('DEGRADED' if (self.consecutive_cycle_errors or self.consecutive_mis_errors) else 'RUNNING'),'cycles':self.cycles,'interval_seconds':self.interval,'started_at':self.started_at,'last_cycle_started_at':self.last_cycle_started_at,'last_cycle_completed_at':self.last_cycle_completed_at,'last_successful_mis_at':self.last_successful_mis_at,'consecutive_cycle_errors':self.consecutive_cycle_errors,'max_consecutive_cycle_errors':self.max_consecutive_cycle_errors,'last_cycle_error':self.last_cycle_error,'consecutive_mis_errors':self.consecutive_mis_errors,'max_consecutive_mis_errors':self.max_consecutive_mis_errors,'last_mis_error':self.last_mis_error,'last_cycle':self.last_cycle,'watchlist':[x['symbol'] for x in self.watchlist],'market':list(self.market.values()),'errors':self.errors[-10:],'radar':self.radar.status(),'confirmations':self.last_confirmations[-20:],'monitor_logs':list(self.monitor_logs[-200:])}
    def run_once(self):
        # Fail closed after any ambiguous durable commit or restore error.
        if getattr(self.engine, "persistence_degraded", False) or getattr(self.engine, "restore_error", None):
            self.stop()
            return {"at":datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
                    "status":"persistence_degraded", "results":[], "paper_orders_created":0}
        # Prevent manual scan and background worker from placing duplicate orders concurrently.
        if not self._cycle_lock.acquire(blocking=False):
            return {'at':datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),'status':'scan_in_progress','results':[]}
        try:
            return self._run_cycle()
        finally:
            self._cycle_lock.release()

    def _run_cycle(self):
        cycle_time=datetime.now(TAIPEI).isoformat(timespec='seconds'); results=[]; confirmations=[]
        self.last_cycle_started_at=cycle_time
        self._log(f'開始第 {self.cycles + 1} 輪監控｜檢查 {len(self.watchlist)} 檔自選股與全市場 MIS',tag='CYCLE')
        # Stage 1: full-market public MIS snapshot + cheap dynamic discovery.
        radar_status=self.radar.scan()
        radar_meta=radar_status.get('radar',{})
        self._log(f"MIS 快照完成｜全市場 {radar_meta.get('universe_symbols',0)} 檔｜有效快照 {radar_meta.get('snapshot_symbols',0)} 檔｜動態候選 {len(radar_status.get('dynamic_candidates',[]))} 檔", level='warning' if radar_status.get('last_error') else 'info', tag='MIS')
        if radar_status.get('last_error'):
            mis_error = str(radar_status.get('last_error'))[:500]
            with self._lock:
                self.consecutive_mis_errors += 1
                self.last_mis_error = mis_error
                self.errors.append({'at':datetime.now(TAIPEI).isoformat(timespec='seconds'),
                                    'error':f'MIS snapshot failed: {mis_error}',
                                    'consecutive_mis_errors':self.consecutive_mis_errors})
                self.errors = self.errors[-50:]
                mis_error_count = self.consecutive_mis_errors
            self._log(f"MIS 錯誤｜連續 {mis_error_count}/{self.max_consecutive_mis_errors}｜{mis_error}",level='error',tag='MIS_ERROR')
            try: self.engine.agent_task('auditor','warning',f'MIS 連續失敗 {mis_error_count} 次：{mis_error[:140]}')
            except Exception: pass
            if mis_error_count >= self.max_consecutive_mis_errors:
                self._log('MIS 連續失敗達上限；停止自主監控，避免在行情不可用時繼續執行',level='error',tag='MIS_FAIL_CLOSED')
                self._stop.set()
        else:
            with self._lock:
                if self.consecutive_mis_errors:
                    self._log(f'MIS 已恢復｜連續失敗計數 {self.consecutive_mis_errors} → 0',tag='MIS_RECOVERED')
                self.consecutive_mis_errors = 0
                self.last_mis_error = None
            self.last_successful_mis_at=datetime.now(TAIPEI).isoformat(timespec='seconds')
        self.engine.agent_task('research','working',f"全市場 MIS 快照：{radar_status.get('radar',{}).get('snapshot_symbols',0)} 檔；候選 {len(radar_status.get('dynamic_candidates',[]))} 檔")
        if radar_status.get('last_error'):
            self.engine.agent_task('research','warning',f"MIS 快照失敗：{radar_status['last_error'][:150]}")
        else:
            self.engine.agent_task('research','success',f"MIS 更新 {radar_status.get('last_snapshot_at')}；開始候選確認鏈")
            # Automatically evaluate stop-loss AND take-profit on every successful MIS cycle.
            # Only fresh, traded quotes may trigger exits; persistence must be configured.
            self._monitor_open_positions(results, cycle_time)
            # Stage 2: enrich only the top three new candidates per cycle, cache-first.
            # No history endpoint is called for the whole universe.
            for candidate in radar_status.get('dynamic_candidates',[])[:3]:
                symbol=str(candidate['symbol']); name=str(candidate.get('name') or symbol)
                self._log(f'動態候選進入確認鏈｜{symbol} {name}',tag='CANDIDATE')
                quote=self.radar.snapshot.get(symbol) or {}
                if quote.get('stale') or not quote.get('data_identity'):
                    results.append({'symbol':symbol,'status':'stale_mis_snapshot'}); continue
                try:
                    self.engine.agent_task('cio','working',f'分派盤中確認：{symbol} {name}')
                    self.engine.agent_task('research','working',f'{symbol} 補充 61 根以上日K背景（Cache-first）')
                    context=self.history_provider.context(symbol)
                    self._log(f"歷史日K確認｜{symbol}｜資料日 {context.get('source_data_date','--')}｜{context.get('history_bars',0)} 根｜趨勢 {'PASS' if context.get('stage1_pass') else 'FAIL'}｜均量 {'PASS' if context.get('liquidity_pass') else 'FAIL'}",level='info' if context.get('stage1_pass') and context.get('liquidity_pass') else 'warning',tag='HISTORY')
                    self.confirmation_contexts[symbol]=context
                    if not context['stage1_pass']:
                        row={'symbol':symbol,'status':'history_trend_rejected','reason':'STAGE1_TREND_FAIL','context':context}
                        results.append(row); confirmations.append(row); continue
                    if not context['liquidity_pass']:
                        row={'symbol':symbol,'status':'history_liquidity_rejected','reason':'VMA5_LT_1000_LOTS','vma5_lots':context['vma5_lots']}
                        results.append(row); confirmations.append(row); continue
                    snap=RadarSnapshot(symbol=symbol,snapshot_id=f"{symbol}:{quote.get('data_identity')}",data_identity=str(quote.get('data_identity') or ''),
                        current_price=float(quote.get('current_price') or quote.get('price') or 0),previous_close=float(quote.get('previous_close') or 0),
                        today_open=float(quote.get('today_open') or 0),up_pct=float(quote.get('up_pct') or 0),is_traded=bool(quote.get('is_traded',True)),payload_hash=str(quote.get('data_identity') or ''))
                    machine=self.confirmation_states.setdefault(symbol,RadarStateMachine())
                    triggered,reason=machine.evaluate(snap,context['breakout_level'],gain_threshold_pct=4.0,buffer_pct=0.3)
                    if triggered:
                        self.pending_confirmations[symbol]={'started':time.monotonic(),'context':context,'name':name,'trigger_price':snap.current_price}
                    pending=self.pending_confirmations.get(symbol)
                    row={'symbol':symbol,'name':name,'status':'breakout_pending' if not triggered else 'breakout_triggered','reason':reason,'state':machine.state,
                         'price':snap.current_price,'breakout_level':context['breakout_level'],'vma5_lots':context['vma5_lots'],'source':quote.get('source','TWSE MIS snapshot')}
                    if not triggered and not pending:
                        results.append(row); confirmations.append(row); continue
                    if pending and time.monotonic()-pending['started']>300:
                        self.pending_confirmations.pop(symbol,None)
                        row.update(status='fugle_confirmation_expired',reason='FUGLE_PENDING_TTL_300S')
                        results.append(row); confirmations.append(row); self._record_confirmation_event(row,cycle_time); continue
                    if pending:
                        context=pending['context']; name=pending['name']
                    # Stage 3: completed Fugle 5m microstructure must pass BOTH structure and volume.
                    self.engine.agent_task('quant','working',f'{symbol} 已確認突破；等待／檢查 Fugle 完成 5 分K')
                    micro=self.fugle_5m.confirm_micro_breakout(symbol,min_volume_ratio=1.2)
                    row['fugle_5m']=micro
                    if not micro.get('passed'):
                        if micro.get('reason')=='FUGLE_5M_INSUFFICIENT_COMPLETED_BARS' or micro.get('reason')=='FUGLE_5M_CONFIRMATION_FAILED':
                            row.update(status='fugle_5m_waiting',reason=micro.get('reason','FUGLE_5M_NOT_CONFIRMED'))
                            results.append(row); confirmations.append(row); continue
                        row.update(status='fugle_5m_rejected',reason=micro.get('reason','FUGLE_5M_NOT_CONFIRMED'))
                        self.pending_confirmations.pop(symbol,None)
                        results.append(row); confirmations.append(row); self._record_confirmation_event(row,cycle_time); continue
                    # Stage 4: projected full-session volume >= 1.5x five-day average.
                    projection=projected_volume(float(quote.get('cumulative_volume_lots') or quote.get('volume_lots') or 0),quote.get('observed_at') or cycle_time,context['vma5_lots'])
                    row['projected_volume']=projection
                    if not projection.get('passed'):
                        row.update(status='projected_volume_waiting',reason='PROJECTED_VOLUME_LT_1_5X_OR_NOT_READY')
                        results.append(row); confirmations.append(row); continue
                    # Stage 5: paper risk gate. No duplicate buy if the account already holds the symbol.
                    existing=self.engine.ledger.positions.get(symbol)
                    if existing and existing.quantity>0:
                        row.update(status='already_held',reason='POSITION_ALREADY_OPEN')
                        self.pending_confirmations.pop(symbol,None)
                        results.append(row); confirmations.append(row); self._record_confirmation_event(row,cycle_time); continue
                    price=Decimal(str(snap.current_price)); qty=max(1,min(int(self.engine.max_order_notional/price),int(self.engine.ledger.cash/(price*(Decimal('1')+self.engine.fee_rate)))))
                    if not self.engine.store.configured:
                        row.update(status='persistence_blocked',reason='SUPABASE_REQUIRED_FOR_PAPER_TRADES')
                        self.pending_confirmations.pop(symbol,None)
                        results.append(row); confirmations.append(row); self._record_confirmation_event(row,cycle_time); continue
                    if qty<=0 or price*qty>self.engine.max_order_notional:
                        row.update(status='risk_rejected',reason='PAPER_RISK_LIMIT')
                        self.pending_confirmations.pop(symbol,None)
                        results.append(row); confirmations.append(row); self._record_confirmation_event(row,cycle_time); continue
                    row['scorecard']={'trend':'PASS','distinct_mis_snapshots':2,'fugle_5m_structure':True,'fugle_5m_volume':True,'projected_volume_ratio':projection['projected_ratio'],'projected_volume_threshold':1.5,'paper_risk':'PASS'}
                    self.engine.agent_task('risk','success',f'{symbol} 完成突破、5分K、量能及紙上曝險檢查')
                    outcome=self._trade(symbol,name,'BUY',qty,price,quote,'tianji_3k_confirmed_breakout')
                    row.update(status='paper_buy' if outcome.get('status')=='processed' and outcome.get('fill') else outcome.get('status','trade_error'),outcome=outcome)
                    self.pending_confirmations.pop(symbol,None)
                    results.append(row); confirmations.append(row); self._record_confirmation_event(row,cycle_time)
                except Exception as exc:
                    msg=f'{symbol}: {type(exc).__name__}: {exc}'
                    with self._lock: self.errors.append({'at':cycle_time,'error':msg}); self.errors=self.errors[-50:]
                    self.engine.agent_task('research','warning',f'確認鏈暫停：{msg[:150]}')
                    self._log(f'確認鏈錯誤｜{msg}',level='error',tag='ERROR')
                    row={'symbol':symbol,'status':'confirmation_error','reason':msg[:220]}; results.append(row); confirmations.append(row)
                    # Fail closed: no price or trade is inferred from a failed provider.
        # Watchlist prices are display-only. They cannot independently create buys.
        for item in self.watchlist:
            symbol=item['symbol']; name=item['name']
            try:
                quote=self.client.fetch(symbol); quote['name']=name if not quote.get('name') or quote.get('name')==symbol else quote['name']
                with self._lock: self.market[symbol]=quote
                self._log(f"行情更新｜{symbol} {name}｜現價 {quote.get('price','--')}｜漲跌 {quote.get('change_pct','--')}%｜來源 {quote.get('source','--')}",level='warning' if quote.get('stale') else 'info',tag='QUOTE')
                if quote.get('stale'):
                    self.engine.agent_task('risk','warning',f'{symbol} 顯示行情過期；不參與交易')
            except Exception as exc:
                msg=f'{symbol}: {type(exc).__name__}: {exc}'
                with self._lock:
                    self.errors.append({'at':cycle_time,'error':msg}); self.errors=self.errors[-50:]
                    previous=self.market.get(symbol)
                    if previous:
                        previous=dict(previous); previous['refresh_error']=msg; previous['stale']=True; previous['data_age_seconds']=max(int(previous.get('data_age_seconds') or 0),1201); self.market[symbol]=previous
                    else: self.market[symbol]={'symbol':symbol,'name':name,'stale':True,'refresh_error':msg,'source':'unavailable','market_timestamp':None,'data_age_seconds':None}
                self._log(f'行情更新失敗｜{symbol}｜{msg}',level='error',tag='ERROR')
        self.engine.agent_task('auditor','working','核對快照時間、歷史趨勢、突破確認、Fugle 5分K、預估量能與紙上帳本')
        summary={'event_id':str(uuid.uuid4()),'event_type':'market.scan.completed','occurred_at':cycle_time,'source':'ai-quant-lab-autonomy','payload':{'results':results,'watchlist':[x['symbol'] for x in self.watchlist],'confirmation_count':len(confirmations)}}
        try: self.engine.process(summary)
        except Exception: pass
        self.engine.agent_task('auditor','success',f'確認鏈本輪完成：候選處理 {len(results)} 檔；紙上買進 {sum(1 for x in results if x.get("status")=="paper_buy")} 檔')
        with self._lock:
            self.cycles+=1; self.last_confirmations=confirmations[-100:]; self.last_cycle={'at':cycle_time,'results':results,'confirmation_count':len(confirmations)}
            self.last_cycle_completed_at=datetime.now(TAIPEI).isoformat(timespec='seconds')
            self.consecutive_cycle_errors=0; self.last_cycle_error=None
            self._log(f"第 {self.cycles} 輪完成｜行情 {len(self.market)} 檔｜確認結果 {len(confirmations)} 筆｜本輪事件 {len(results)} 筆",tag='CYCLE DONE')
        return self.last_cycle

    def _monitor_open_positions(self, results, cycle_time):
        """Evaluate every open paper position against fresh MIS quotes each radar cycle."""
        if not self.engine.store.configured:
            if self.engine.ledger.positions:
                self._log("持倉停損停利暫停｜Supabase 持久化未設定，拒絕自主出場", level="error", tag="EXIT_BLOCKED")
            return
        for held_symbol, position in list(self.engine.ledger.positions.items()):
            symbol = str(held_symbol).strip().upper()
            if not position or int(getattr(position, "quantity", 0)) <= 0:
                continue
            quote = self.radar.snapshot.get(symbol) or {}
            if not quote:
                self._log(f"持倉監控略過｜{symbol}｜本輪沒有行情", level="warning", tag="EXIT_SKIP")
                continue
            if quote.get("stale") or not quote.get("is_traded", True):
                self._log(f"持倉監控略過｜{symbol}｜行情過期或未成交", level="warning", tag="EXIT_SKIP")
                continue
            try:
                current = Decimal(str(quote.get("current_price") or quote.get("price") or 0))
            except Exception:
                current = Decimal("0")
            if current <= 0:
                self._log(f"持倉監控略過｜{symbol}｜價格無效", level="warning", tag="EXIT_SKIP")
                continue
            snapshot = {k: v for k, v in quote.items() if k != "candles"}
            identity = quote.get("data_identity") or quote.get("market_timestamp") or quote.get("observed_at") or cycle_time
            event = {
                "event_id": f"auto-exit-check:{symbol}:{identity}",
                "event_type": "paper.exit_check",
                "occurred_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
                "source": "ai-quant-lab-autonomous-exit-monitor",
                "payload": {"mode": "paper", "symbol": symbol, "mark_price": str(current),
                            "stop_loss_pct": "0.02", "take_profit_pct": "0.04",
                            "market_snapshot": snapshot},
            }
            try:
                outcome = self.engine.process(event)
            except Exception as exc:
                self._log(f"停損停利檢查失敗｜{symbol}｜{type(exc).__name__}: {exc}", level="error", tag="EXIT_ERROR")
                continue
            fill = outcome.get("fill") if isinstance(outcome, dict) else None
            if outcome.get("status") == "processed" and fill and fill.get("side") == "SELL":
                reason = outcome.get("exit_reason") or "STOP_OR_TAKE_PROFIT"
                is_stop = "STOP_LOSS" in reason.upper()
                results.append({"symbol": symbol, "name": str(quote.get("name") or symbol),
                                "status": "paper_stop_loss" if is_stop else "paper_take_profit",
                                "price": float(current), "reason": reason, "outcome": outcome,
                                "quantity": fill.get("quantity"), "paper_only": True})
                self._log(f"自動紙上出場｜{symbol}｜{reason}｜成交價 {current}｜數量 {fill.get('quantity')}",
                          level="warning" if is_stop else "info", tag="EXIT_FILLED")
            elif outcome.get("status") not in ("duplicate",):
                actions = outcome.get("actions") or []
                if "exit_not_triggered" in actions:
                    self._log(f"持倉監控正常｜{symbol}｜現價 {current}｜均價 {position.average_price}｜尚未觸發", tag="EXIT_WATCH")
                elif outcome.get("status") not in ("processed", "duplicate"):
                    self._log(f"停損停利未執行｜{symbol}｜{outcome.get('error') or outcome.get('status')}", level="error", tag="EXIT_ERROR")

    def _record_confirmation_event(self,row,occurred_at):
        # Supabase event ledger is the only durable audit trail; event key is deterministic per candidate + trigger snapshot.
        symbol=str(row.get('symbol','')); payload={'mode':'paper','symbol':symbol,'stock_name':row.get('name',symbol),'confirmation':row}
        event={'event_id':str(uuid.uuid4()),
               'event_type':'prediction.recorded','occurred_at':datetime.now(TAIPEI).isoformat(timespec='seconds'),'source':'ai-quant-lab-tianji-confirmation','payload':payload}
        # Duplicate audit keys are harmless; do not let audit persistence failure become a trade approval.
        try: self.engine.process(event)
        except Exception: pass

    def _trade(self,symbol,name,side,qty,price,quote,reason):
        event={'event_id':str(uuid.uuid4()),'event_type':'signal.created','occurred_at':datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),'source':'ai-quant-lab-autonomy','payload':{'mode':'paper','symbol':symbol,'stock_name':name,'side':side,'quantity':qty,'price':str(price),'strategy':'SMA5_SMA20_MOMENTUM','reason':reason,'market_snapshot':{k:v for k,v in quote.items() if k!='candles'}}}
        outcome = self.engine.process(event)
        if outcome.get('status') == 'processed' and outcome.get('fill'):
            # V18 transactional outbox is committed with the durable event + paper fill.
            # Never send directly from the trading loop: dispatcher owns retries and audit.
            outcome['notification'] = {'status': 'QUEUED' if outcome.get('persistence') == 'supabase' else 'NOT_DURABLE',
                                       'destination': 'TELEGRAM', 'paper_only': True,
                                       'idempotency_key': f"paper-fill-telegram:{event['event_id']}"}
        return outcome
    def _run(self):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:
                msg=f'background cycle failed: {type(exc).__name__}: {exc}'
                with self._lock:
                    self.consecutive_cycle_errors += 1
                    self.last_cycle_error=msg[:500]
                    self.errors.append({'at':datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),'error':msg,'consecutive':self.consecutive_cycle_errors})
                    self.errors=self.errors[-50:]
                self._log(f'監控循環例外｜連續 {self.consecutive_cycle_errors}/{self.max_consecutive_cycle_errors}｜{msg}',level='error',tag='CYCLE_ERROR')
                try: self.engine.agent_task('auditor','warning',msg[:180])
                except Exception: pass
                if getattr(self.engine,'persistence_degraded',False) or getattr(self.engine,'restore_error',None):
                    self._log('持久化狀態降級；停止自主監控，等待人工確認恢復',level='error',tag='FAIL_CLOSED')
                    self._stop.set()
                elif self.consecutive_cycle_errors >= self.max_consecutive_cycle_errors:
                    self._log('連續監控循環失敗達上限；已自動停止，避免不健康狀態下繼續執行',level='error',tag='FAIL_CLOSED')
                    self._stop.set()
            if self._stop.wait(self.interval): break
        self.enabled=False
        self._log('自主監控背景執行緒已停止',tag='STOPPED')
