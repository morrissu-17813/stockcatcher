<script setup>
import { computed, onMounted, onUnmounted, ref, watch, nextTick, reactive } from 'vue'
import { createChart } from 'lightweight-charts'

const API = 'http://127.0.0.1:8765'
const roleDefaults = [
  { id:'cio', name:'天機總指揮', role:'CIO', coat:'奶油白長毛', accessory:'策略指揮', task:'統籌團隊與策略', avatar:'/agents/cio-sprite.png', color:'#e8d9b8', seat:0, routine:0 },
  { id:'quant', name:'量化研究員', role:'QUANT', coat:'黑白短毛', accessory:'量化模型', task:'計算趨勢與量能', avatar:'/agents/quant-sprite.png', color:'#d8e0eb', seat:1, routine:1 },
  { id:'research', name:'產業研究員', role:'RESEARCH', coat:'金棕長毛', accessory:'產業情報', task:'整理產業資料', avatar:'/agents/research-sprite.png', color:'#f0d0a4', seat:2, routine:2 },
  { id:'risk', name:'風控長', role:'RISK', coat:'深咖啡長毛', accessory:'風險監控', task:'檢查交易風險', avatar:'/agents/risk-sprite.png', color:'#c8a28c', seat:3, routine:3 },
  { id:'execution', name:'交易執行員', role:'EXECUTION', coat:'黑金短毛', accessory:'模擬交易', task:'等待合格交易訊號', avatar:'/agents/execution-sprite.png', color:'#d6c6b0', seat:4, routine:4 },
  { id:'auditor', name:'驗證員', role:'AUDITOR', coat:'淺灰白長毛', accessory:'稽核驗證', task:'核對事件與成交紀錄', avatar:'/agents/auditor-sprite.png', color:'#d9dce8', seat:5, routine:5 },
]
const roles = ref(roleDefaults.map(r => ({ ...r, status:'idle', motion:'sit', motionLabel:'坐姿工作', motionSource:'ambient', taskStartedAt:null })))
const events = ref([])
const apiOnline = ref(false)
const autonomyOn = ref(false)
const busy = ref(false)
const sessionCount = ref(0)
const persistenceInfo = ref({status:'尚未檢查',ok:false,session_id:null,parent_session_id:null})
const checkpointBusy = ref(false)
const checkpointMessage = ref('尚未建立本次 Session 檢查點')
const notificationInfo = ref({ok:false,enabled:false,worker_alive:false,queue:[],stats:{},error:null})
const cash = ref(1000000)
const positions = ref(0)
const realizedPnl = ref(0)
const equity = ref(1000000)
const equityHistory = ref([])
const lastDataFreshness = ref('等待行情')
const totalEvents = ref(0)
const fillCount = ref(0)
const currentView = ref('office')
const selectedSymbol = ref('')
const chartMode = ref('candles')
const chartContainer = ref(null)
const benchmarkData = ref([])
const benchmarkErrors = ref([])
const benchmarkUpdatedAt = ref('尚未同步全球行情')
const chartReady = ref(false)
let tvChart = null, tvSeries = null, tvVolumeSeries = null, maSeries = [], chartResizeObserver = null, chartNeedsFit = true, lastChartSymbol = ''
const market = ref([])
const selectedHistory = ref([])
const historySource = ref('尚未載入歷史日K')
const historyLoading = ref(false)
const historyError = ref('')
let historySymbolRequested = ''
const marketUpdatedAt = ref('尚未取得行情')
const radarCandidates = ref([])
const radarStats = ref({})
const monitorLogs = ref([])
const monitorLogFilter = ref('全部')
const researchTools = ref([])
const researchToolName = ref('')
const researchParams = reactive({})
const researchFields = computed(() => {
  const schema = researchTools.value.find(t => t.name === researchToolName.value)?.inputSchema || {}
  return Object.entries(schema.properties || {}).map(([name, spec]) => ({ name, title: spec.title || spec.description || name, type: spec.type || 'string', required: (schema.required || []).includes(name), description: spec.description || '', enum: Array.isArray(spec.enum) ? spec.enum : [] })).slice(0, 12)
})
const researchResult = ref(null)
const researchBusy = ref(false)
const researchError = ref('')
const researchQuery = ref('')
const researchAgent = ref('research')
const researchDisplay = computed(() => normalizeResearchOutput(researchResult.value?.result ?? researchResult.value))
const confirmationRows = ref([])
const productionSignals = ref([])
const productionSignalStatus = ref({path_exists:false, configured_path:'', last_error:null})
const productionAudit = ref({prediction_count:0,validated_count:0,ground_truth_available_count:0,ground_truth_missing_count:0,signals:[]})
const productionAuditBusy = ref(false)
const productionImportResult = ref(null)
const decisionJournal = ref({signal_count:0,agent_record_count:0,journals:[]})
const decisionJournalBusy = ref(false)
const decisionJournalResult = ref(null)
const geminiReview = ref(null)
const geminiBusy = ref(false)
const signalValidation = ref(null)
const signalValidationBusy = ref(false)
const signalValidationError = ref('')
const validationGeminiReview = ref(null)
const validationGeminiBusy = ref(false)
const backtestBusy = ref(false)
const backtestReport = ref(null)
const backtestError = ref('')
const confirmationStatusText = s => ({breakout_pending:'等待第二筆快照',breakout_triggered:'突破觸發',fugle_5m_waiting:'等待5分K確認',projected_volume_waiting:'等待量能達標',paper_buy:'紙上買進',fugle_5m_rejected:'5分K未通過',history_trend_rejected:'趨勢不符',history_liquidity_rejected:'均量不足',already_held:'已有持倉',persistence_blocked:'持久化未就緒',paper_stop_loss:'紙上停損',confirmation_error:'確認鏈異常'})[s] || s || '待確認'
const lastError = ref('')
const lastEvent = computed(() => events.value[0] || null)
// Restore lightweight UI-only state after refresh. Authoritative engine/session state
// still comes from the backend and Supabase; localStorage is not used as a trading ledger.
const UI_SNAPSHOT_KEY = 'tianji-ai-quant-lab-ui-v1'
let visibilityHandler = null
function restoreUiSnapshot() {
  try {
    const raw = localStorage.getItem(UI_SNAPSHOT_KEY)
    if (!raw) return
    const snap = JSON.parse(raw)
    if (snap.version !== 1) return
    if (['office','market','research','ledger'].includes(snap.currentView)) currentView.value = snap.currentView
    if (typeof snap.selectedSymbol === 'string') selectedSymbol.value = snap.selectedSymbol.slice(0, 16)
    if (['candles','line','area'].includes(snap.chartMode)) chartMode.value = snap.chartMode
    if (['全部','錯誤','訊號'].includes(snap.monitorLogFilter)) monitorLogFilter.value = snap.monitorLogFilter
    if (typeof snap.researchToolName === 'string') researchToolName.value = snap.researchToolName.slice(0, 160)
    if (typeof snap.researchQuery === 'string') researchQuery.value = snap.researchQuery.slice(0, 300)
    if (['cio','quant','research','risk','execution','auditor'].includes(snap.researchAgent)) researchAgent.value = snap.researchAgent
    if (snap.researchParams && typeof snap.researchParams === 'object' && !Array.isArray(snap.researchParams)) Object.assign(researchParams, snap.researchParams)
    if (snap.geminiReview && typeof snap.geminiReview === 'object') geminiReview.value = snap.geminiReview
    if (snap.backtestReport && typeof snap.backtestReport === 'object') backtestReport.value = snap.backtestReport
    if (snap.researchResult && typeof snap.researchResult === 'object') researchResult.value = snap.researchResult
    if (typeof snap.researchError === 'string') researchError.value = snap.researchError.slice(0, 1000)
    if (snap.decisionJournal && typeof snap.decisionJournal === 'object') decisionJournal.value = snap.decisionJournal
    if (snap.decisionJournalResult && typeof snap.decisionJournalResult === 'object') decisionJournalResult.value = snap.decisionJournalResult
    if (snap.productionImportResult && typeof snap.productionImportResult === 'object') productionImportResult.value = snap.productionImportResult
    if (typeof snap.backtestError === 'string') backtestError.value = snap.backtestError.slice(0, 1000)
    if (snap.signalValidation && typeof snap.signalValidation === 'object') signalValidation.value = snap.signalValidation
    if (snap.validationGeminiReview && typeof snap.validationGeminiReview === 'object') validationGeminiReview.value = snap.validationGeminiReview
    if (typeof snap.signalValidationError === 'string') signalValidationError.value = snap.signalValidationError.slice(0, 1000)
  } catch (_) { /* malformed/blocked browser storage must never block Lab startup */ }
}
function persistUiSnapshot() {
  try {
    const snap = { version:1, saved_at:new Date().toISOString(), currentView:currentView.value,
      selectedSymbol:selectedSymbol.value, chartMode:chartMode.value, monitorLogFilter:monitorLogFilter.value,
      researchToolName:researchToolName.value, researchQuery:researchQuery.value, researchAgent:researchAgent.value,
      researchParams:{...researchParams}, geminiReview:geminiReview.value, backtestReport:backtestReport.value,
      researchResult:researchResult.value, researchError:researchError.value, decisionJournal:decisionJournal.value,
      decisionJournalResult:decisionJournalResult.value, productionImportResult:productionImportResult.value,
      backtestError:backtestError.value, signalValidation:signalValidation.value, signalValidationError:signalValidationError.value,
      validationGeminiReview:validationGeminiReview.value }
    let encoded = JSON.stringify(snap)
    if (encoded.length > 450000) {
      snap.researchParams = {}; snap.geminiReview = null; snap.backtestReport = null; snap.researchResult = null
      snap.decisionJournal = {signal_count:0,agent_record_count:0,journals:[]}; snap.decisionJournalResult = null
      snap.productionImportResult = null; encoded = JSON.stringify(snap)
    }
    if (encoded.length <= 450000) localStorage.setItem(UI_SNAPSHOT_KEY, encoded)
  } catch (_) { /* quota/private-mode errors are non-fatal */ }
}
watch([currentView, selectedSymbol, chartMode, monitorLogFilter, researchToolName, researchQuery, researchAgent,
  researchParams, geminiReview, backtestReport, researchResult, researchError, decisionJournal, decisionJournalResult,
  productionImportResult, backtestError, signalValidation, signalValidationError, validationGeminiReview], persistUiSnapshot, {deep:true})
// Coordinates are normalized to the visible office floor and aligned to illustrated desks.
const defaultAgentCoordinates = {
  cio:       { x: 29, y: 27 }, // strategy workstation, upper-left
  quant:     { x: 17, y: 57 }, // quant workstation, left
  research:  { x: 36, y: 29 }, // research workstation, window side
  risk:      { x: 29, y: 82 }, // risk workstation, lower-left
  execution: { x: 76, y: 69 }, // execution workstation, lower-right
  auditor:   { x: 83, y: 52 }, // audit workstation, right
}
const zoneAgentCoordinates = {
  COMMAND_CENTER: defaultAgentCoordinates,
  ANALYST_DESKS: defaultAgentCoordinates,
  TRADING_DESK: defaultAgentCoordinates,
  RISK_OFFICE: defaultAgentCoordinates,
  AUDIT_STATION: defaultAgentCoordinates,
  DEBATE_TABLE: { cio:{x:43,y:48}, quant:{x:47,y:38}, research:{x:57,y:38}, risk:{x:59,y:49}, execution:{x:58,y:60}, auditor:{x:43,y:60} },
  COFFEE_CORNER: { cio:{x:88,y:28}, quant:{x:88,y:28}, research:{x:88,y:28}, risk:{x:88,y:28}, execution:{x:88,y:28}, auditor:{x:88,y:28} },
  LOUNGE: { cio:{x:82,y:30}, quant:{x:82,y:30}, research:{x:82,y:30}, risk:{x:82,y:30}, execution:{x:82,y:30}, auditor:{x:82,y:30} },
}
function isCoffeeBreak(r) {
  if (r.status !== 'idle') return false
  // Short staggered visual tea breaks, one Agent at a time; no trading state is changed.
  const now = new Date()
  return (now.getMinutes() % 6) === (Number(r.routine) % 6) && now.getSeconds() < 45
}
function agentPoint(r) {
  if (isCoffeeBreak(r)) return zoneAgentCoordinates.COFFEE_CORNER[r.id]
  const zone = r.target_zone ? zoneAgentCoordinates[r.target_zone] : null
  return (zone && zone[r.id]) || defaultAgentCoordinates[r.id] || { x:50, y:50 }
}
function agentStageStyle(r) {
  const p = agentPoint(r)
  return { left:`${p.x}%`, top:`${p.y}%`, '--agent-accent':r.color, '--move-duration':r.status==='working'?'650ms':'900ms' }
}
const activeLinks = computed(() => {
  const flow = [['cio','quant'],['quant','research'],['research','risk'],['risk','execution'],['execution','auditor'],['cio','risk']]
  return flow.map(([from,to], index) => { const a=roles.value.find(r=>r.id===from), b=roles.value.find(r=>r.id===to); const p=agentPoint(a), q=agentPoint(b); const active=[a,b].some(r=>['working','warning','success'].includes(r.status)); return {id:`${from}-${to}`,x1:p.x,y1:p.y,x2:q.x,y2:q.y,active,index} }).filter(link=>link.active)
})
const selectedMarket = computed(() => market.value.find(m => String(m.symbol).replace(/\.(TW|TWO)$/i,'') === String(selectedSymbol.value).replace(/\.(TW|TWO)$/i,'')) || market.value[0] || null)
const chartGeometry = computed(() => {
  const rows = (selectedMarket.value?.candles || []).filter(c => Number.isFinite(Number(c.close)))
  if (rows.length < 2) return { line: '', area: '', points: [], candles: [] }
  const values = rows.map(c => Number(c.close)); const lows = rows.map(c => Number(c.low ?? c.close)); const highs = rows.map(c => Number(c.high ?? c.close));
  const lo = Math.min(...lows); const hi = Math.max(...highs); const span = hi - lo || 1
  const points = values.map((v, i) => ({ x: i * 700 / (values.length - 1), y: 190 - ((v - lo) / span) * 165, value: v, time: rows[i].timestamp }))
  const line = points.map((pt, i) => `${i ? 'L' : 'M'}${pt.x.toFixed(2)} ${pt.y.toFixed(2)}`).join(' ')
  const candles = rows.map((c,i) => { const x= i * 700 / rows.length + 350 / rows.length; const y=v=>190-((Number(v??c.close)-lo)/span)*165; return { x, openY:y(c.open), closeY:y(c.close), highY:y(c.high), lowY:y(c.low), up:Number(c.close)>=Number(c.open), width:Math.max(2,Math.min(9,560/rows.length)) } })
  return { line, area: `${line} L700 210 L0 210 Z`, points, candles }
})
function selectStock(stock) { selectedSymbol.value = String(stock?.symbol || '').replace(/\.(TW|TWO)$/i,''); if (!selectedSymbol.value) return; loadSelectedHistory(true) }
async function loadSelectedHistory(force=false) {
  const symbol = normalizedCode(selectedSymbol.value || selectedMarket.value?.symbol)
  if (!symbol || (!force && historySymbolRequested === symbol)) return
  historySymbolRequested = symbol; historyLoading.value = true; historyError.value = ''
  try { const data = await request(`/api/market/history?symbol=${encodeURIComponent(symbol)}`); selectedHistory.value = data.candles || []; historySource.value = `${data.source || '歷史資料'} · ${data.bars || selectedHistory.value.length} 根 · 更新至 ${data.latest_date || '--'}`; chartNeedsFit = true; updateTradingViewChart() }
  catch (err) { selectedHistory.value = []; historyError.value = String(err.message || err); historySource.value = '歷史日K取得失敗；目前可用盤中 K 線'; }
  finally { historyLoading.value = false }
}

const normalizedCode = v => String(v || '').replace(/\.(TW|TWO)$/i, '')
const selectedConfirmation = computed(() => {
  const code = normalizedCode(selectedSymbol.value)
  return confirmationRows.value.find(r => normalizedCode(r.symbol) === code) || null
})
const breakthroughMarkers = computed(() => {
  const row = selectedConfirmation.value
  if (!row) return []
  const status = String(row.status || '')
  if (!['breakout_triggered','paper_buy','fugle_5m_waiting','projected_volume_waiting'].includes(status)) return []
  const candles = chartMode.value === 'candles' && selectedHistory.value.length ? selectedHistory.value : (selectedMarket.value?.candles || [])
  if (!candles.length) return []
  // The confirmation chain currently does not persist a canonical trigger candle timestamp.
  // Mark the latest available candle as a live status badge rather than fabricating a historical time.
  const raw = candles[candles.length - 1]?.date || candles[candles.length - 1]?.timestamp
  const parsed = chartTime(raw)
  if (!parsed) return []
  const label = status === 'paper_buy' ? '3K PASS・紙上買進' : status === 'breakout_triggered' ? '3K 突破' : '3K 確認中'
  return [{ time: parsed, position: 'aboveBar', color: status === 'paper_buy' ? '#e7c27e' : '#ffb45b', shape: 'arrowUp', text: label }]
})
function chartTime(stamp) {
  if (stamp == null || stamp === '') return null
  const raw = typeof stamp === 'number' ? (stamp > 1e12 ? stamp : stamp * 1000) : stamp
  const ms = typeof raw === 'number' ? raw : new Date(raw).getTime()
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null
}
function smaData(rows, period) {
  const result = []
  let running = 0
  for (let i = 0; i < rows.length; i++) {
    running += Number(rows[i].close)
    if (i >= period) running -= Number(rows[i - period].close)
    if (i >= period - 1) result.push({ time: rows[i].time, value: running / period })
  }
  return result
}
function formatRadarPrice(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '—'
  return numeric.toLocaleString('zh-TW', { maximumFractionDigits: 2 })
}

function formatRadarPercent(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '—'
  return numeric.toFixed(2)
}

function formatBenchmarkValue(item) {
  if (item?.value == null || !Number.isFinite(Number(item.value))) return '資料暫缺'
  const digits = item.key === 'usdtwd' ? 4 : 2
  return Number(item.value).toLocaleString('zh-TW', { maximumFractionDigits: digits })
}
function formatBenchmarkChange(item) {
  if (item?.change_pct == null || !Number.isFinite(Number(item.change_pct))) {
    return item?.ok ? '漲跌幅未提供' : '資料來源暫缺'
  }
  const value = Number(item.change_pct)
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}
function formatPrice(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return Number(value).toLocaleString('zh-TW', { maximumFractionDigits: 2 })
}
function formatPercent(value, positiveOnly = false) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const n = Number(value)
  return `${n > (positiveOnly ? 0 : -0.0000001) ? '+' : ''}${n.toFixed(2)}%`
}

function sparklinePoints(item) {
  const values = (item?.history || []).map(Number).filter(Number.isFinite)
  if (values.length < 2) return ''
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1
  return values.map((value, index) => `${(index * 100 / (values.length - 1)).toFixed(2)},${(25 - ((value - lo) / span) * 21).toFixed(2)}`).join(' ')
}
function initTradingViewChart() {
  if (!chartContainer.value || tvChart) return
  try {
    tvChart = createChart(chartContainer.value, {
      autoSize: true,
      layout: { background: { color: '#07121c' }, textColor: '#9fb6c9', fontFamily: 'DM Mono, Noto Sans TC, monospace', fontSize: 11 },
      grid: { vertLines: { color: '#172f40' }, horzLines: { color: '#172f40' } },
      rightPriceScale: { borderColor: '#244658', scaleMargins: { top: .10, bottom: .24 } },
      timeScale: { borderColor: '#244658', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 1 }, handleScroll: true, handleScale: true,
      localization: { locale: 'zh-TW' }
    })
    if (chartMode.value === 'intraday') {
      tvSeries = tvChart.addLineSeries({ color: '#69d8b5', lineWidth: 2, priceLineVisible: true, lastValueVisible: true, crosshairMarkerRadius: 3 })
    } else {
      tvSeries = tvChart.addCandlestickSeries({ upColor: '#2fc99a', downColor: '#ff736f', borderUpColor: '#2fc99a', borderDownColor: '#ff736f', wickUpColor: '#2fc99a', wickDownColor: '#ff736f' })
      const colors = ['#f0c66e', '#b990ff', '#5fbeff', '#e28ba6']
      maSeries = [5, 10, 20, 60].map((period, i) => tvChart.addLineSeries({ color: colors[i], lineWidth: period <= 10 ? 2 : 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: `MA${period}` }))
      tvVolumeSeries = tvChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'volume', priceLineVisible: false, lastValueVisible: false })
      tvChart.priceScale('volume').applyOptions({ scaleMargins: { top: .80, bottom: 0 }, visible: false, borderVisible: false })
      tvChart.priceScale('right').applyOptions({ scaleMargins: { top: .08, bottom: .25 } })
    }
    chartReady.value = true
    updateTradingViewChart()
    if (typeof ResizeObserver !== 'undefined') {
      chartResizeObserver = new ResizeObserver(() => { if (tvChart) tvChart.timeScale().fitContent() })
      chartResizeObserver.observe(chartContainer.value)
    }
  } catch (err) { lastError.value = `TradingView 圖表初始化失敗：${err.message || err}` }
}
function updateTradingViewChart() {
  if (!tvChart || !tvSeries) return
  const activeSymbol = String(selectedMarket.value?.symbol || '')
  if (activeSymbol !== lastChartSymbol) { lastChartSymbol = activeSymbol; chartNeedsFit = true }
  const sourceRows = chartMode.value === 'candles' && selectedHistory.value.length ? selectedHistory.value : (selectedMarket.value?.candles || [])
  const rows = sourceRows
    .map(c => ({ ...c, time: chartTime(c.date || c.timestamp) }))
    .filter(c => c.time && Number.isFinite(Number(c.close)))
    .sort((a, b) => a.time - b.time)
  if (!rows.length) {
    chartNeedsFit = true
    tvSeries.setData([])
    maSeries.forEach(series => series.setData([]))
    tvVolumeSeries?.setData([])
    return
  }
  if (chartMode.value === 'intraday') {
    tvSeries.setData(rows.map(c => ({ time: c.time, value: Number(c.close) })))
  } else {
    tvSeries.setData(rows.map(c => ({ time: c.time, open: Number(c.open ?? c.close), high: Number(c.high ?? c.close), low: Number(c.low ?? c.close), close: Number(c.close) })))
    ;[5, 10, 20, 60].forEach((period, i) => maSeries[i]?.setData(smaData(rows, period)))
    if (tvVolumeSeries) tvVolumeSeries.setData(rows.map(c => ({ time: c.time, value: Number(c.volume || 0), color: Number(c.close) >= Number(c.open ?? c.close) ? '#2fc99a88' : '#ff736f88' })))
  }
  if (tvSeries.setMarkers) tvSeries.setMarkers(chartMode.value === 'candles' ? breakthroughMarkers.value : [])
  if (chartNeedsFit) { tvChart.timeScale().fitContent(); chartNeedsFit = false }
}
watch(chartMode, async () => {
  chartResizeObserver?.disconnect(); chartResizeObserver = null; chartNeedsFit = true; lastChartSymbol = ''
  if (tvChart) { tvChart.remove(); tvChart = null; tvSeries = null; tvVolumeSeries = null; maSeries = [] }
  await nextTick(); initTradingViewChart()
})
watch([selectedMarket, breakthroughMarkers, selectedHistory], () => updateTradingViewChart(), { deep: true })
watch(selectedSymbol, () => loadSelectedHistory())
async function refreshMonitorAndResearch() {
  try {
    const status = await request('/api/market')
    monitorLogs.value = status.monitor_logs || []
  } catch (_) { /* main health poll reports API status */ }
  try { const feed = await request('/api/production/signals'); productionSignals.value = feed.signals || []; productionSignalStatus.value = feed } catch (_) { /* surfaced through API health */ }
  try { productionAudit.value = await request('/api/production/audit') } catch (err) { productionAudit.value = { ...productionAudit.value, error:err.message } }
}
const filteredMonitorLogs = computed(() => {
  const rows = monitorLogs.value || []
  if (monitorLogFilter.value === '錯誤') return rows.filter(x => /error|failed|失敗|異常|warning/i.test(`${x.level} ${x.message}`))
  if (monitorLogFilter.value === '訊號') return rows.filter(x => /3K|突破|候選|確認|PASS|paper/i.test(x.message || ''))
  return rows
})
async function refreshProductionAudit() {
  productionAuditBusy.value = true; productionImportResult.value = null
  try { productionAudit.value = await request('/api/production/audit') }
  catch (err) { productionAudit.value = { ...productionAudit.value, error:err.message }; lastError.value = err.message }
  finally { productionAuditBusy.value = false }
}
async function importProductionAudit() {
  productionAuditBusy.value = true; productionImportResult.value = null
  try {
    productionImportResult.value = await request('/api/production/import', { method:'POST', body:JSON.stringify({}) })
    await refreshState(); await refreshProductionAudit()
  } catch (err) { productionImportResult.value = { ok:false, error:err.message }; lastError.value = err.message }
  finally { productionAuditBusy.value = false }
}
async function previewDecisionJournal() {
  decisionJournalBusy.value = true; decisionJournalResult.value = null
  try { decisionJournal.value = await request('/api/production/decisions?limit=30') }
  catch (err) { decisionJournalResult.value = {ok:false,error:err.message}; lastError.value = err.message }
  finally { decisionJournalBusy.value = false }
}
async function persistDecisionJournal() {
  decisionJournalBusy.value = true; decisionJournalResult.value = null
  try {
    decisionJournalResult.value = await request('/api/production/decisions/generate', {method:'POST',body:JSON.stringify({limit:30})})
    decisionJournal.value = decisionJournalResult.value
    await refreshState()
  } catch (err) { decisionJournalResult.value = {ok:false,error:err.message}; lastError.value = err.message }
  finally { decisionJournalBusy.value = false }
}
async function runGeminiReview() {
  const signal = productionAudit.value.signals?.[0]
  if (!signal?.prediction_id) { lastError.value = '目前沒有可供 Gemini 覆核的 prediction_id'; return }
  geminiBusy.value = true; geminiReview.value = null
  try { geminiReview.value = await request('/api/agents/gemini-review', {method:'POST',body:JSON.stringify({prediction_id:signal.prediction_id,agent:'research'})}); await refreshState() }
  catch (err) { geminiReview.value = {ok:false,error:err.message}; lastError.value = err.message }
  finally { geminiBusy.value = false }
}
async function validateTaiBiaoSignal() {
  signalValidationBusy.value = true; signalValidationError.value = ''
  try {
    const data = await request('/api/production/validate-signal', {method:'POST', body:JSON.stringify({symbol:'6278', signal_date:'2026-10-07', signal_price:250.5, horizon_days:7, stop_loss_pct:2})})
    signalValidation.value = data.report || data
    if (!data.ok) signalValidationError.value = data.report?.error || data.error || '驗證資料不足'
  } catch (err) { signalValidationError.value = String(err.message || err) }
  finally { signalValidationBusy.value = false }
}
function validationPct(value) { const n=Number(value); return Number.isFinite(n)?`${n.toFixed(1)}%`:'—' }
async function rerunGeminiOnValidation() {
  if (!signalValidation.value?.ok) { signalValidationError.value = '請先完成事後驗證'; return }
  validationGeminiBusy.value = true; validationGeminiReview.value = null
  try { validationGeminiReview.value = await request('/api/agents/gemini-review-validation', {method:'POST', body:JSON.stringify({validation_report:signalValidation.value})}) }
  catch (err) { validationGeminiReview.value = {ok:false,error:String(err.message || err)} }
  finally { validationGeminiBusy.value = false }
}
function auditPrice(value) { const n=Number(value); return Number.isFinite(n)&&n>0?n.toLocaleString('zh-TW',{maximumFractionDigits:2}):'—' }
function auditPct(value) { const n=Number(value); return Number.isFinite(n)?`${n.toFixed(2)}%`:'—' }
function auditRatio(value) { const n=Number(value); return Number.isFinite(n)?`${n.toFixed(2)}×`:'—' }
function auditValidationLabel(row) { if (row.ground_truth_available) return row.ground_truth_3k ? 'Ground Truth PASS' : 'Ground Truth FAIL'; return row.validation_status==='NOT_VALIDATED'?'尚未驗證':'缺少 Ground Truth' }
async function loadResearchTools() {
  try {
    const data = await request('/api/research/tools')
    researchTools.value = data.tools || []
    if (!researchToolName.value && researchTools.value.length) researchToolName.value = researchTools.value[0].name
    researchError.value = data.error || ''
  } catch (err) { researchError.value = String(err.message || err) }
}
async function runResearchTool() {
  researchBusy.value = true; researchError.value = ''; researchResult.value = null
  try {
    const args = {}
    for (const field of researchFields.value) {
      const value = researchParams[field.name]
      if (value === undefined || value === null || value === '') continue
      args[field.name] = field.type === 'number' || field.type === 'integer' ? Number(value) : field.type === 'boolean' ? value === true || value === 'true' : value
    }
    if (researchQuery.value.trim()) {
      const key = ['stock_id','stock','query','stock_ids','stocks','symbol','ticker'].find(k => researchFields.value.some(f => f.name === k))
      if (key && (args[key] === undefined || args[key] === '')) args[key] = researchQuery.value.trim()
    }
    researchResult.value = await request('/api/agents/research', { method:'POST', body:JSON.stringify({agent:researchAgent.value, tool:researchToolName.value, arguments:args}) })
  } catch (err) { researchError.value = String(err.message || err) }
  finally { researchBusy.value = false }
}
function normalizeResearchOutput(value) {
  let data = value
  // MCP often wraps useful content in content[].text; parse JSON text when possible.
  if (data && typeof data === 'object' && Array.isArray(data.content)) {
    const texts = data.content.filter(x => x && typeof x.text === 'string').map(x => x.text)
    if (texts.length === 1) { try { data = JSON.parse(texts[0]) } catch { data = {內容:texts[0]} } }
    else if (texts.length) data = texts.map((text, index) => ({項目:index + 1,內容:text}))
  }
  if (typeof data === 'string') { try { data = JSON.parse(data) } catch { data = {內容:data} } }
  if (data && typeof data === 'object' && !Array.isArray(data) && data.result !== undefined && Object.keys(data).length <= 4) data = data.result
  if (Array.isArray(data)) return { kind:'table', rows:data.map((row, index) => row && typeof row === 'object' ? row : {項目:index + 1,內容:row}) }
  if (data && typeof data === 'object') {
    const arrayEntry = Object.entries(data).find(([,v]) => Array.isArray(v) && v.length && v.every(x => x && typeof x === 'object'))
    if (arrayEntry) return { kind:'table', title:arrayEntry[0], rows:arrayEntry[1], summary:Object.entries(data).filter(([k,v]) => k !== arrayEntry[0] && (v == null || typeof v !== 'object')).map(([label,value]) => ({label,value})) }
    return { kind:'cards', rows:Object.entries(data).map(([label,value]) => ({label,value:formatResearchValue(value)})) }
  }
  return { kind:'cards', rows:[{label:'查詢結果',value:String(data ?? '無資料')}] }
}
function formatResearchValue(value) {
  if (value == null || typeof value !== 'object') return value == null || value === '' ? '—' : String(value)
  if (Array.isArray(value)) return value.map(v => typeof v === 'object' ? formatResearchValue(v) : String(v)).join('、')
  return Object.entries(value).map(([k,v]) => `${humanizeResearchKey(k)}：${v && typeof v === 'object' ? formatResearchValue(v) : v}`).join('；')
}
function researchCell(value) {
  if (value == null || value === '') return '—'
  if (typeof value === 'object') return formatResearchValue(value)
  return String(value)
}
function humanizeResearchKey(key) { return String(key).replaceAll('_',' ').replace(/(symbol|stock id)/i,'股票代號').replace(/(price|close)/i,'價格').replace(/(volume)/i,'成交量').replace(/(date|timestamp)/i,'資料日期').replace(/(name)/i,'名稱') }
function researchColumns(rows) {
  return [...new Set(rows.flatMap(row => Object.keys(row || {})))].slice(0, 8)
}
function researchAgentName(id) { return ({cio:'天機總指揮',quant:'量化研究員',research:'產業研究員',risk:'風控長',execution:'交易執行員',auditor:'驗證員'})[id] || id }
function researchToolHint(tool) {
  const props = Object.keys(tool?.inputSchema?.properties || {})
  return props.length ? `可填寫 ${props.length} 項研究條件` : '此工具不需要額外參數'
}
async function refreshBenchmarks() {
  if (document.hidden) return
  try {
    const result = await request('/api/benchmarks')
    benchmarkData.value = result.items || []
    benchmarkErrors.value = result.errors || []
    benchmarkUpdatedAt.value = result.updated_at ? new Date(Number(result.updated_at) * 1000).toLocaleTimeString('zh-TW',{hour12:false}) : '尚未同步全球行情'
  } catch (err) {
    benchmarkErrors.value = [String(err.message || err)]
  }
}

const equityLine = computed(() => { const a=equityHistory.value; if(a.length<2)return ''; const lo=Math.min(...a), hi=Math.max(...a), span=hi-lo||1; return a.map((v,i)=>`${i?'L':'M'}${(i*100/(a.length-1)).toFixed(2)} ${(38-((v-lo)/span)*30).toFixed(2)}`).join(' ') })
const money = n => new Intl.NumberFormat('zh-TW', { style:'currency', currency:'TWD', maximumFractionDigits:0 }).format(Number(n || 0))
const statusText = s => ({ idle:'待命', working:'工作中', success:'已完成', warning:'風險警示' })[s] || s || '待命'
const motionText = m => ({ sit:'坐姿工作', think:'思考中', stand:'起身', walk:'移動中', report:'報告中', return:'返回座位', alert:'警示處理', celebrate:'任務完成' })[m] || '工作中'
let pollHandle, benchmarkHandle, choreographyHandle, choreographyIndex = 0, lastMotionSignature = ''
// Track only timers that are still pending; fired timers remove themselves.
const pendingTimers = new Set()

function clearAmbientTimers() {
  for (const timerId of pendingTimers) window.clearTimeout(timerId)
  pendingTimers.clear()
}
function pauseAmbientMotion() {
  clearAmbientTimers()
  // Invalidate any scheduled sequence so a stale callback cannot move an Agent later.
  for (const role of roles.value) {
    role.ambientRunId = null
    if (role.motionSource === 'ambient' && role.motion !== 'sit') setMotion(role, 'sit', 'ambient')
  }
}
function setMotion(role, motion, source='ambient') {
  role.motion = motion
  role.motionLabel = motionText(motion)
  role.motionSource = source
}
function planAmbientMotion() {
  if (document.hidden) return
  if (!roles.value.length) return
  const role = roles.value[choreographyIndex % roles.value.length]
  choreographyIndex++
  if (role.status === 'working' || role.status === 'warning' || role.motionSource === 'runtime') return
  // A deliberate office routine: review screen -> stand -> visit side console -> report -> return to desk.
  // These are ambience-only motions and never create Agent work or trades.
  const sequence = [
    { motion: 'think', delay: 0 },
    { motion: 'stand', delay: 1400 },
    { motion: 'walk', delay: 2600 },
    { motion: 'report', delay: 4700 },
    { motion: 'return', delay: 6200 },
    { motion: 'sit', delay: 8200 },
  ]
  const runId = `${role.id}-${Date.now()}`
  role.ambientRunId = runId
  sequence.forEach(({ motion, delay }) => {
    let timerId
    timerId = window.setTimeout(() => {
      pendingTimers.delete(timerId)
      if (role.ambientRunId !== runId || role.status === 'working' || role.status === 'warning' || role.motionSource === 'runtime') return
      setMotion(role, motion, 'ambient')
    }, delay)
    pendingTimers.add(timerId)
  })
}
function applyRuntimeMotion(role, status, task) {
  role.ambientRunId = null
  if (status === 'warning') { setMotion(role, 'alert', 'runtime'); return }
  if (status === 'working') {
    const text = String(task || '')
    setMotion(role, /報告|交付|回報|完成|核對結果/.test(text) ? 'report' : /分派|統籌|全局/.test(text) ? 'stand' : 'think', 'runtime')
    return
  }
  if (status === 'success') { setMotion(role, 'celebrate', 'runtime'); return }
  if (role.motionSource === 'runtime') setMotion(role, 'sit', 'ambient')
}
async function request(path, options={}) {
  const response = await fetch(`${API}${path}`, { headers:{'Content-Type':'application/json', ...(options.headers||{})}, ...options })
  const result = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`)
  return result
}
async function refreshState() {
  if (document.hidden) return
  try {
    const state = await request('/api/state')
    apiOnline.value = true; lastError.value = ''
    persistenceInfo.value = state.persistence_v17 || persistenceInfo.value
    notificationInfo.value = await request('/api/notifications/status').catch(err => ({ok:false,enabled:false,worker_alive:false,queue:[],stats:{},error:String(err.message || err)}))
    totalEvents.value = state.counts?.events || 0; fillCount.value = state.counts?.fills || 0
    cash.value = Number(state.ledger?.cash || 0); equity.value = Number(state.ledger?.equity || 0); equityHistory.value = [...equityHistory.value, equity.value].slice(-60)
    realizedPnl.value = Number(state.ledger?.realized_pnl || 0)
    positions.value = (state.ledger?.positions || []).filter(p => p.quantity > 0).length
    for (const sr of state.roles || []) {
      const role = roles.value.find(r => r.id === sr.role_id)
      if (!role) continue
      const changed = role.status !== sr.status || role.task !== sr.task
      role.status = sr.status; role.task = sr.task; role.target_zone = sr.target_zone || null; role.bubble = sr.bubble || (['working','warning','success'].includes(sr.status) ? sr.task : '')
      if (changed) applyRuntimeMotion(role, sr.status, sr.task)
    }
    events.value = (state.events || []).map(e => ({ id:e.event_id, time:new Date(e.processed_at || e.occurred_at).toLocaleTimeString('zh-TW',{hour12:false}), type:e.event_type, message:e.result?.error || `${e.status} · ${e.source}` }))
    autonomyOn.value = Boolean(state.autonomy?.enabled)
    const status = await request('/api/market').catch(() => null)
    if (status) { autonomyOn.value = Boolean(status.enabled); market.value = status.market || []; if (!selectedSymbol.value && market.value.length) { selectedSymbol.value = String(market.value[0].symbol || '').replace(/\.(TW|TWO)$/i,''); loadSelectedHistory(); } if (selectedSymbol.value && !market.value.some(m => String(m.symbol).replace(/\.(TW|TWO)$/i,'') === selectedSymbol.value) && market.value.length) selectedSymbol.value = String(market.value[0].symbol || '').replace(/\.(TW|TWO)$/i,''); radarCandidates.value = status.radar?.dynamic_candidates || []; radarStats.value = status.radar?.radar || {}; confirmationRows.value = status.confirmations || []; monitorLogs.value = status.monitor_logs || []; marketUpdatedAt.value = status.radar?.last_snapshot_at || status.last_cycle?.at || (status.market?.length ? '行情已取得，等待下一輪' : '等待首次掃描'); const fresh=status.market?.filter(q=>!q.stale).length||0; lastDataFreshness.value = `${fresh}/${status.market?.length||0} 檔資料有效` }
  } catch (err) { apiOnline.value = false; lastError.value = String(err.message || err) }
}
async function createPersistenceCheckpoint() {
  checkpointBusy.value = true
  try {
    const result = await request('/api/persistence/checkpoint', {method:'POST', body:'{}'})
    checkpointMessage.value = `檢查點 #${result.checkpoint_seq} 已保存 · 事件序號 ${result.last_event_seq}`
    const state = await request('/api/persistence')
    persistenceInfo.value = {...persistenceInfo.value, ...(state.persistence || {}), session_id:state.session_id, parent_session_id:state.parent_session_id}
  } catch (err) { checkpointMessage.value = `檢查點失敗：${String(err.message || err)}` }
  finally { checkpointBusy.value = false }
}
async function toggleAutonomy() {
  busy.value = true
  try {
    const result = await request(autonomyOn.value ? '/api/autonomy/stop' : '/api/autonomy/start', { method:'POST', body:'{}' })
    autonomyOn.value = autonomyOn.value ? false : Boolean(result.started)
    if (!result.started && result.error) lastError.value = result.error
    events.value.unshift({ id:crypto.randomUUID(), time:new Date().toLocaleTimeString('zh-TW',{hour12:false}), type:'AUTONOMY', message:autonomyOn.value ? '已啟動自主行情掃描（模擬交易）' : '已送出停止自主掃描指令' })
    await refreshState()
  } catch (err) { lastError.value = String(err.message || err) }
  finally { busy.value = false }
}
async function scanOnce() {
  busy.value = true
  try { const result = await request('/api/autonomy/scan-once',{method:'POST',body:'{}'}); events.value.unshift({id:crypto.randomUUID(),time:new Date().toLocaleTimeString('zh-TW',{hour12:false}),type:'SCAN',message:`單次掃描完成：${(result.results||[]).length} 檔`}); await refreshState() }
  catch(err) { lastError.value=String(err.message||err) } finally { busy.value=false }
}
async function demoCycle() {
  if (busy.value) return
  busy.value = true
  try {
    const result = await request('/api/demo', { method:'POST', body:JSON.stringify({symbol:'2330',side:'BUY',quantity:10,price:100}) })
    sessionCount.value++; await refreshState()
    if (result.status !== 'processed') lastError.value = result.error || result.status
  } catch (err) { lastError.value = String(err.message || err) }
  finally { busy.value = false }
}
async function runSelectedBacktest() {
  if (!selectedSymbol.value) { backtestError.value = '請先選擇股票'; return }
  backtestBusy.value = true; backtestError.value = ''; backtestReport.value = null
  try { const data = await request(`/api/backtest?symbol=${encodeURIComponent(selectedSymbol.value)}`); if (!data.ok) throw new Error(data.report?.error || data.error || '回測未完成'); backtestReport.value = data.report }
  catch (err) { backtestError.value = String(err.message || err) }
  finally { backtestBusy.value = false }
}
async function generateReport() {
  try { const result=await request('/api/report'); events.value.unshift({id:crypto.randomUUID(),time:new Date().toLocaleTimeString('zh-TW',{hour12:false}),type:'REPORT',message:`報告已產生 · ${result.persistence || 'memory-only-dev'}`}) }
  catch(err) { lastError.value=String(err.message||err) }
}
function clearEvents(){events.value=[]}
onMounted(() => {
  restoreUiSnapshot(); refreshState(); refreshBenchmarks(); refreshMonitorAndResearch(); loadResearchTools(); nextTick(initTradingViewChart)
  pollHandle=window.setInterval(refreshState,2500)
  benchmarkHandle=window.setInterval(refreshBenchmarks,60000)
  choreographyHandle=window.setInterval(planAmbientMotion,1800)
  visibilityHandler=() => {
    if (document.hidden) {
      pauseAmbientMotion()
      return
    }
    // Resume from a clean state; do not replay motions that elapsed while hidden.
    refreshState(); refreshBenchmarks(); refreshMonitorAndResearch()
  }
  document.addEventListener('visibilitychange', visibilityHandler)
})
onUnmounted(() => {
  if(pollHandle)clearInterval(pollHandle)
  if(benchmarkHandle)clearInterval(benchmarkHandle)
  if(choreographyHandle)clearInterval(choreographyHandle)
  if(visibilityHandler)document.removeEventListener('visibilitychange', visibilityHandler)
  pauseAmbientMotion()
  chartResizeObserver?.disconnect(); tvChart?.remove()
})
</script>

<template>
  <main class="lab-shell">
    <header class="topbar">
      <a class="brand" href="#market-terminal" aria-label="天機 AI Quant Lab 總覽">
        <div class="brand-mark" aria-hidden="true">天</div>
        <div><p class="eyebrow">GOOD TRADE · GOOD LIFE · BETTER US</p><h1>天機 <span>AI Quant Lab</span></h1></div>
      </a>
      <nav class="top-nav" aria-label="研究室導覽">
        <a class="nav-chip active" href="#market-terminal">總覽</a>
        <a class="nav-chip" href="#market-terminal">個股研究</a>
        <a class="nav-chip" href="#lab-radar">3K 監控</a>
        <a class="nav-chip" href="#paper-ledger">交易紀錄</a>
        <a class="nav-chip" href="#ai-office">六大 Agent</a>
      </nav>
      <div class="top-status"><span class="live-led" :class="{off:!apiOnline}"></span><span>{{apiOnline?'LAB API 已連線':'API 離線'}}</span><b class="status-divider">/</b><span>{{autonomyOn?'自主研究運作中':'研究待命'}}</span><b class="paper-pill">PAPER ONLY</b></div>
    </header>

    <section class="market-section" aria-label="全球市場行情">
      <div class="section-kicker"><div><span class="eyebrow">GLOBAL MARKET MONITOR</span><h2>全球市場總覽</h2></div><span class="updated-label"><i></i>{{benchmarkUpdatedAt}}</span></div>
      <div class="benchmark-strip">
        <div v-for="item in benchmarkData" :key="item.key" class="benchmark-tile" :class="{'benchmark-error':!item.ok}" :title="item.error || item.source">
          <span class="benchmark-name">{{item.name}}</span>
          <strong :class="item.change_pct>=0?'positive':'negative'">{{ formatBenchmarkValue(item) }}</strong>
          <div class="benchmark-change" :class="item.change_pct>=0?'positive':'negative'">{{ formatBenchmarkChange(item) }}</div>
          <svg class="benchmark-spark" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true"><polyline v-if="sparklinePoints(item)" :points="sparklinePoints(item)" :class="item.change_pct>=0?'spark-up':'spark-down'"/></svg>
          <small class="benchmark-source">{{item.source || '資料來源待連線'}}</small>
        </div>
      </div>
      <div class="summary-strip">
        <div class="summary-tile"><span class="summary-icon">◈</span><div><small>監控股池</small><strong>{{market.length || 0}} <em>檔</em></strong></div><span class="summary-sub">{{lastDataFreshness}}</span></div>
        <div class="summary-tile"><span class="summary-icon gold-icon">＄</span><div><small>模擬資產 · 紙上交易</small><strong>{{money(equity)}}</strong></div><span class="summary-sub" :class="realizedPnl>=0?'positive':'negative'">已實現 {{money(realizedPnl)}}</span></div>
        <div class="summary-tile"><span class="summary-icon">◷</span><div><small>台北時間</small><strong>{{new Date().toLocaleTimeString('zh-TW',{hour12:false})}}</strong></div><span class="summary-sub">{{marketUpdatedAt}}</span></div>
      </div>
      <div class="summary-strip persistence-strip">
        <div class="summary-tile"><span class="summary-icon">⛨</span><div><small>V17 持久化 Session</small><strong>{{persistenceInfo.ok ? '已持久化' : '未就緒'}}</strong></div><span class="summary-sub">{{persistenceInfo.status || '等待狀態'}}</span></div>
        <div class="summary-tile"><span class="summary-icon">↻</span><div><small>本次執行 Session</small><strong>{{persistenceInfo.session_id ? persistenceInfo.session_id.slice(0,8) : '—'}}</strong></div><span class="summary-sub">{{persistenceInfo.parent_session_id ? '已連結前次 Session' : '首次／尚未恢復'}}</span></div>
        <div class="summary-tile persistence-action"><div><small>恢復檢查點</small><strong>{{checkpointMessage}}</strong></div><button class="btn-secondary" :disabled="checkpointBusy || !persistenceInfo.ok" @click="createPersistenceCheckpoint">{{checkpointBusy ? '保存中…' : '立即建立檢查點'}}</button></div>
        <div class="summary-tile"><span class="summary-icon">↗</span><div><small>V18 通知派送</small><strong>{{notificationInfo.worker_alive ? '派送中' : notificationInfo.enabled ? '待命' : '未啟用'}}</strong></div><span class="summary-sub">{{notificationInfo.error || `送達 ${notificationInfo.stats?.sent || 0} · 待重試 ${notificationInfo.stats?.retry_pending || 0} · 不確定 ${notificationInfo.stats?.unknown || 0}`}}</span></div>
      </div>
    </section>

    <section id="market-terminal" class="trading-workbench" aria-label="市場研究終端">
      <aside class="terminal-sidebar">
        <div class="sidebar-brand"><span>⌂</span><b>研究中心</b></div>
        <a class="sidebar-link active" href="#market-terminal"><span>◫</span>市場總覽</a>
        <a class="sidebar-link" href="#watchlist-panel"><span>▤</span>監控股池</a>
        <a class="sidebar-link" href="#lab-radar"><span>⌁</span>3K 突破</a>
        <a class="sidebar-link" href="#paper-ledger"><span>▣</span>交易紀錄</a>
        <a class="sidebar-link" href="#research-events"><span>⌕</span>即時事件</a>
        <a class="sidebar-link" href="#ai-office"><span>♧</span>產業研究</a>
        <div class="sidebar-safety"><span class="safety-dot"></span><b>安全模式</b><small>不連接券商<br/>不送出實盤委託</small></div>
      </aside>

      <section class="central-board chart-panel" aria-label="TradingView 技術圖表">
        <div class="chart-panel-head">
          <div class="chart-stock-heading"><span class="symbol-chip">{{selectedMarket?.symbol || selectedSymbol || '—'}}</span><div><h2>{{selectedMarket?.name || '等待行情資料'}}</h2><span>{{selectedMarket?.source || '等待行情來源'}}</span></div></div>
          <div class="chart-current-price"><strong>{{ formatPrice(selectedMarket?.price) }}</strong><span :class="Number(selectedMarket?.change_pct)>=0?'positive':'negative'">{{selectedMarket?.change_pct!=null?formatPercent(selectedMarket.change_pct):'等待報價'}}</span></div>
        </div>
        <div class="chart-toolbar"><div class="chart-mode-switch"><button :class="{active:chartMode==='intraday'}" @click="chartMode='intraday'">分時</button><button :class="{active:chartMode==='candles'}" @click="chartMode='candles'">技術 K 線</button></div><span class="timeframe-note">{{chartMode==='intraday'?'盤中價格走勢':'OHLC · MA5 / 10 / 20 / 60 · VOL'}}</span><span class="three-k-chip" :class="selectedConfirmation?.status==='paper_buy'?'passed':selectedConfirmation?.status==='breakout_triggered'?'triggered':''">{{selectedConfirmation?confirmationStatusText(selectedConfirmation.status):'3K 待觸發'}}</span></div>
        <div v-if="chartMode==='candles'" class="ma-legend"><span class="ma5">━ MA5</span><span class="ma10">━ MA10</span><span class="ma20">━ MA20</span><span class="ma60">━ MA60</span><span class="vol-label">▥ 成交量</span></div>
        <div class="chart-canvas"><div ref="chartContainer" class="tradingview-chart" role="img" :aria-label="`${selectedMarket?.symbol || ''} ${chartMode==='intraday'?'盤中走勢':'K 線技術圖'}`"></div><div v-if="!(chartMode==='candles' ? (selectedHistory.length || selectedMarket?.candles?.length) : selectedMarket?.candles?.length)" class="chart-empty">{{selectedMarket?.stale?'行情資料已過期':selectedMarket?'此標的暫無可用 K 線':'等待行情 API 回傳資料'}}</div><div class="chart-footer"><span>{{chartMode==='candles' ? historySource : (selectedMarket?.market_timestamp || '尚未更新')}} · {{chartMode==='candles' && historyLoading ? '載入歷史日K…' : selectedMarket?.stale?'資料過期':'行情來源時間'}}</span><span>TradingView Lightweight Charts</span></div><div v-if="breakthroughMarkers.length" class="breakout-legend"><i></i>{{breakthroughMarkers[0].text}} <small>（最新可用 K 棒狀態）</small></div></div>
      </section>

      <aside id="watchlist-panel" class="watch-panel">
        <div class="panel-title-row"><div><span class="eyebrow">LIVE WATCHLIST</span><h3>監控股池</h3></div><span class="count-badge">{{market.length}}</span></div>
        <div class="watch-columns"><span>代號 / 名稱</span><span>現價</span><span>漲跌</span></div>
        <div class="watchlist">
          <button v-for="m in market.slice(0,10)" :key="m.symbol" class="watch-row" :class="{'watch-row-selected':String(m.symbol).replace(/\.(TW|TWO)$/i,'')===selectedSymbol}" @click="selectStock(m)">
            <span class="watch-stock"><b>{{String(m.symbol).replace(/\.(TW|TWO)$/i,'')}}</b><small>{{m.name || '監控標的'}}</small></span><b class="watch-price">{{ formatPrice(m.price) }}</b><em :class="Number(m.change_pct)>=0?'positive':'negative'">{{m.change_pct!=null?formatPercent(m.change_pct,true):'—'}}</em>
          </button>
          <div v-if="!market.length" class="watch-empty">行情資料載入中；離線或過期資料不會觸發模擬交易。</div>
        </div>
        <div class="watch-panel-foot"><i></i>點選標的切換技術圖</div>
        <section class="monitor-log-panel" aria-label="監控記錄">
          <div class="panel-title-row monitor-log-heading"><div><span class="eyebrow">LIVE ACTION LOG</span><h3>監控記錄</h3></div><span class="count-badge">{{monitorLogs.length}}</span></div>
          <div class="monitor-log-toolbar"><span :class="['monitor-state-dot', {active:autonomyOn}]"></span><span>{{autonomyOn ? 'Actions 執行中' : '監控待命'}}</span><select v-model="monitorLogFilter" aria-label="監控記錄篩選"><option>全部</option><option>訊號</option><option>錯誤</option></select></div>
          <div class="monitor-log-list">
            <div v-for="(log, idx) in filteredMonitorLogs.slice().reverse().slice(0,18)" :key="log.id || `${log.at}-${idx}`" class="monitor-log-row" :class="`log-${log.level || 'info'}`"><time>{{log.time || log.at || '--:--:--'}}</time><b>{{log.tag || log.level || 'INFO'}}</b><span>{{log.message}}</span></div>
            <div v-if="!filteredMonitorLogs.length" class="monitor-log-empty">{{autonomyOn ? '已啟動，等待第一輪監控 LOG…' : '按下「啟動自主研究」後，這裡會持續顯示每輪掃描、候選、行情更新與錯誤紀錄。'}}</div>
          </div>
        </section>
      </aside>

      <aside id="research-events" class="events-panel">
        <div class="panel-title-row"><div><span class="eyebrow">EVENT STREAM</span><h3>即時事件流</h3></div><span class="live-event-dot"></span></div>
        <div v-if="!events.length" class="events-empty"><span>◷</span><b>等待真實事件</b><small>啟動研究或執行單次掃描後，這裡會顯示實際處理結果。</small></div>
        <div v-for="e in events.slice(0,8)" :key="e.id" class="event-row"><time>{{e.time}}</time><div><b>{{e.type}}</b><span>{{e.message}}</span></div></div>
        <div class="event-panel-foot"><span class="live-led" :class="{off:!apiOnline}"></span>每 2.5 秒同步 Lab API</div>
      </aside>
    </section>

    <section id="ai-office" class="office-scene">
      <div class="office-header"><div><span class="eyebrow">THE TEAM BEHIND THE SIGNAL</span><h2>天機研究辦公室</h2><p>六位 AI Agent 依照實際任務狀態協作、移動與回報</p></div><div class="office-header-right"><span class="office-live"><i></i>{{autonomyOn?'自主研究運作中':'研究室待命'}}</span><span class="office-time">{{new Date().toLocaleTimeString('zh-TW',{hour12:false})}} <b>台北</b></span></div></div>
      <div class="office-floor">
        <div class="office-image-tint" aria-hidden="true"></div>
        <div class="floor-note floor-note-left"><b>天機工作準則</b><span>紀律・策略・風控・複利</span></div>
        <div class="floor-note floor-note-right"><b>COFFEE CORNER</b><span>休息一下，再分析下一根 K 線</span></div>
        <div class="meeting-label">✦ AI TEAM HUDDLE · 協作討論區 ✦</div>
        <div class="office-zone-label zone-desk-left">QUANT DESK</div>
        <div class="office-zone-label zone-meeting">TEAM TABLE</div>
        <div class="office-zone-label zone-coffee">TEA / COFFEE</div>
        <div class="agent-route-layer" aria-label="由後端 Agent 狀態驅動的辦公室移動圖層">
          <svg class="agent-signal-map" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="agentFlowGradient"><stop offset="0" stop-color="#e4be77"/><stop offset=".5" stop-color="#f6eed8"/><stop offset="1" stop-color="#62caa3"/></linearGradient></defs><line v-for="link in activeLinks" :key="link.id" :x1="link.x1" :y1="link.y1" :x2="link.x2" :y2="link.y2" class="agent-signal-line"/><circle v-for="link in activeLinks" :key="`node-${link.id}`" :cx="(link.x1+link.x2)/2" :cy="(link.y1+link.y2)/2" r=".9" class="agent-signal-node"/></svg>
          <div v-for="r in roles" :key="`route-${r.id}`" class="route-agent" :class="[`route-${r.motion}`, `route-state-${r.status}`]" :style="agentStageStyle(r)"><div v-if="r.bubble" class="route-bubble">{{r.bubble}}</div><img :src="r.avatar" :alt="r.name"/><span>{{isCoffeeBreak(r) ? '☕ 茶歇中' : `${r.role} · ${r.name}`}}</span><i :class="`light-${r.status}`"></i></div>
        </div>
        <div class="office-caption"><span>✦ 日式手繪辦公場景</span><span>原角色素材保留・角色動作由 Lab 狀態驅動</span></div>
      </div>
      <div class="office-bottom">
        <section class="console-panel"><div class="panel-heading"><h3>團隊即時事件</h3><a href="#research-events">完整事件 →</a></div><div v-if="!events.length" class="console-empty">目前尚無事件紀錄。</div><div v-for="e in events.slice(0,5)" :key="`office-${e.id}`" class="console-event"><time>{{e.time}}</time><b>{{e.type}}</b><span>{{e.message}}</span></div></section>
        <section class="console-panel progress-panel"><div class="panel-heading"><h3>六大 Agent 任務進度</h3><span class="muted">狀態同步</span></div><div v-for="r in roles" :key="r.id" class="progress-row"><span>{{r.name}}</span><div><i :class="`bar-${r.status}`" :style="{width:r.status==='success'?'100%':r.status==='working'?'68%':r.status==='warning'?'45%':'20%'}"></i></div><b>{{statusText(r.status)}}</b></div></section>
        <section id="paper-ledger" class="console-panel ledger-panel"><div class="panel-heading"><h3>模擬帳本</h3><span class="paper-label">PAPER ONLY</span></div><div class="ledger-metric"><span>可用現金</span><b>{{money(cash)}}</b></div><div class="ledger-metric"><span>持倉標的</span><b>{{positions}} 檔 · {{fillCount}} 筆成交</b></div><div class="ledger-metric"><span>已實現損益</span><b :class="realizedPnl>=0?'positive':'negative'">{{money(realizedPnl)}}</b></div><div class="ledger-metric"><span>總權益</span><b>{{money(equity)}}</b></div></section>
      </div>
    </section>

    <section id="lab-radar" class="radar-panel" aria-label="全市場盤中雷達">
      <div class="section-kicker"><div><span class="eyebrow">TWSE / TPEX · MIS SNAPSHOT</span><h2>全市場盤中雷達</h2></div><span class="radar-live-badge"><i></i>{{radarStats.snapshot_symbols || 0}} 檔快照</span></div>
      <div class="radar-stats"><span>股票池 <b>{{radarStats.universe_symbols || 0}}</b></span><span>有效快照 <b>{{radarStats.snapshot_symbols || 0}}</b></span><span>動態候選 <b>{{radarCandidates.length}}</b></span><span>批次失敗 <b>{{radarStats.failed_batches ?? '—'}}</b></span></div>
      <div class="radar-columns"><span>代號 / 名稱</span><span>市場</span><span>現價</span><span>漲幅</span></div>
      <div class="radar-candidate-list"><div v-for="c in radarCandidates.slice(0,8)" :key="c.symbol" class="radar-candidate-row"><b>{{c.symbol}}</b><span>{{c.name}}</span><span>{{c.market}}</span><strong>{{formatRadarPrice(c.price)}}</strong><em class="positive">+{{formatRadarPercent(c.up_pct)}}%</em></div><div v-if="!radarCandidates.length" class="watch-empty">等待有效 MIS 快照；候選條件通過不代表 3K PASS 或交易訊號。</div></div>
      <div class="confirmation-strip"><div class="confirmation-heading"><b>交易確認鏈</b><small>雙快照 → 歷史趨勢 → Fugle 5 分 K → 預估量能 ≥ 1.5x → 風控 → 紙上成交</small></div><div class="confirmation-rows"><div v-for="r in confirmationRows.slice(0,8)" :key="r.symbol+'-'+r.status+'-'+r.reason" class="confirmation-row"><b>{{r.symbol}}</b><span>{{r.name || '候選股'}}</span><em :class="['paper_buy','paper_stop_loss'].includes(r.status)?'positive':['confirmation_error','fugle_5m_rejected','risk_rejected'].includes(r.status)?'negative':''">{{confirmationStatusText(r.status)}}</em><small>{{r.reason || '檢查中'}}</small><small v-if="r.projected_volume?.projected_ratio">量能 {{Number(r.projected_volume.projected_ratio).toFixed(2)}}x</small></div><div v-if="!confirmationRows.length" class="watch-empty">尚無通過盤中確認鏈的候選紀錄。</div></div></div>
    </section>

    <section class="signal-bridge-panel">
      <div class="section-kicker"><div><span class="eyebrow">TIANJI 3K · READ ONLY</span><h2>正式版 3K 訊號橋接 V15</h2></div><span class="research-count">{{productionSignalStatus.path_exists ? '資料目錄已找到' : '尚未連接訊號資料'}}</span></div>
      <p class="research-intro">讀取正式版 INTRADAY_3K_PREDICTION 與 PREDICTION_VALIDATION，以 prediction_id 配對。正式版來源完全唯讀；匯入只寫入 AI Quant Lab 的 Supabase 稽核事件，不會建立紙上訂單。</p>
      <div class="signal-bridge-summary"><span>訊號資料目錄</span><strong>{{productionSignalStatus.path_exists ? productionSignalStatus.configured_path : '請設定 TIANJI_3K_DATA_ROOT'}}</strong><span>正式預測筆數</span><strong>{{productionAudit.prediction_count ?? productionSignals.length}}</strong><span>已驗證紀錄</span><strong>{{productionAudit.validated_count ?? 0}}</strong><span>Telegram 已送達</span><strong>{{productionAudit.telegram_sent_count ?? 0}}</strong><span>有 Ground Truth</span><strong>{{productionAudit.ground_truth_available_count ?? 0}}</strong><span>缺少 Ground Truth</span><strong>{{productionAudit.ground_truth_missing_count ?? 0}}</strong></div>
      <div class="production-audit-actions"><button class="btn-secondary" :disabled="productionAuditBusy" @click="refreshProductionAudit">{{productionAuditBusy?'處理中…':'重新稽核正式版紀錄'}}</button><button class="btn-primary" :disabled="productionAuditBusy || !productionSignalStatus.path_exists" @click="importProductionAudit">{{productionAuditBusy?'匯入中…':'匯入 Supabase 稽核帳本'}}</button><span>匯入不等於交易；紙上訂單數固定為 0。</span></div>
      <div v-if="productionAudit.error" class="research-error">{{productionAudit.error}}</div>
      <div v-if="productionImportResult" class="production-import-result" :class="{failed:!productionImportResult.ok}"><b>{{productionImportResult.ok?'匯入流程完成':'匯入未完成'}}</b><span>{{productionImportResult.error || `新增預測 ${productionImportResult.imported_predictions||0} 筆 · 新增驗證 ${productionImportResult.imported_validations||0} 筆 · 重複略過 ${productionImportResult.duplicates||0} 筆 · 紙上訂單 ${productionImportResult.paper_orders_created??0} 筆`}}</span></div>
      <div class="production-audit-table"><div class="production-audit-head"><span>股票／時間</span><span>觸發價／漲幅</span><span>預估量能</span><span>驗證狀態</span></div><div v-for="signal in (productionAudit.signals || []).slice(0,12)" :key="signal.prediction_id" class="production-audit-row"><div><b>{{signal.symbol}} {{signal.name}}</b><small>{{signal.created_at || signal.trade_date || '時間待確認'}}</small><small v-if="signal.dynamic_candidate">盤中動態候選 · {{signal.signal_level || 'EARLY'}}</small></div><div><b>{{auditPrice(signal.current_price)}}</b><small>{{auditPct(signal.up_pct)}}</small></div><div><b>{{auditRatio(signal.projected_ratio)}}</b><small>即時量比 {{auditRatio(signal.live_volume_ratio)}}</small></div><div><b :class="signal.ground_truth_available ? (signal.ground_truth_3k?'audit-pass':'audit-fail') : 'audit-pending'">{{auditValidationLabel(signal)}}</b><small>通知：{{signal.notification_status || '未記錄'}}（閘門 {{signal.notification_gate_status || '未知'}}）</small><small>{{signal.validation_at || '尚無驗證時間'}}</small></div></div><div v-if="!(productionAudit.signals || []).length" class="watch-empty">尚未讀到正式預測事件。請確認 TIANJI_3K_DATA_ROOT 指向含 predictions／validation 的資料根目錄。</div></div>
      <div v-if="productionSignalStatus.last_error" class="research-error">{{productionSignalStatus.last_error}}</div>
      <div class="decision-journal-block">
        <div class="panel-heading"><h3>V16 · 六 Agent 可追溯研究與決策</h3><span class="paper-label">EVIDENCE FIRST</span></div>
        <p class="research-intro">每位 Agent 的結論都連結 prediction_id、可用訊號欄位與未知項。缺少 Ground Truth 或行情路徑時會明確標記，不虛構命中率、MFE/MAE 或基本面事實。</p>
        <div class="production-audit-actions"><button class="btn-secondary" :disabled="decisionJournalBusy || !productionSignalStatus.path_exists" @click="previewDecisionJournal">{{decisionJournalBusy?'處理中…':'預覽決策紀錄'}}</button><button class="btn-primary" :disabled="decisionJournalBusy || !productionSignalStatus.path_exists" @click="persistDecisionJournal">{{decisionJournalBusy?'留存中…':'寫入 Supabase 決策帳本'}}</button><button class="btn-secondary" :disabled="geminiBusy || !productionAudit.signals?.length" @click="runGeminiReview">{{geminiBusy?'Gemini 覆核中…':'Gemini 覆核最新訊號'}}</button><button class="btn-secondary" :disabled="signalValidationBusy" @click="validateTaiBiaoSignal">{{signalValidationBusy?'驗證中…':'驗證台表科 6278（10/7）'}}</button><button class="btn-secondary" :disabled="validationGeminiBusy || !signalValidation?.ok" @click="rerunGeminiOnValidation">{{validationGeminiBusy?'Gemini 二次覆核中…':'Gemini 覆核事後結果'}}</button><span>只寫入 Lab；不建立訂單、不寫正式版資料夾。</span></div>
        <div v-if="geminiReview" class="production-import-result" :class="{failed:!geminiReview.ok}"><b>{{geminiReview.ok?'Gemini 研究覆核已完成':'Gemini 覆核未完成'}}</b><span>{{geminiReview.error || `來源：${geminiReview.provider} / ${geminiReview.model} · 證據 ID：${geminiReview.evidence_id} · 留存：${geminiReview.journal_persistence} · 僅供研究覆核，不可覆蓋風控。`}}</span><pre v-if="geminiReview.review" class="gemini-review-json">{{JSON.stringify(geminiReview.review,null,2)}}</pre></div>
        <div v-if="signalValidation || signalValidationError" class="production-import-result" :class="{failed:!!signalValidationError}">
          <b>台表科 6278 事後驗證 · {{signalValidation?.status || '尚未完成'}}</b>
          <span v-if="signalValidationError">{{signalValidationError}}</span>
          <template v-if="signalValidation?.ok">
            <span>訊號日 {{signalValidation.signal_date}} · 參考價 {{auditPrice(signalValidation.signal_price)}} · 觀察 {{signalValidation.observation_start}} 至 {{signalValidation.observation_end}} · 資料來源 {{signalValidation.data_source}} · 留存 {{signalValidation.persistence}}</span>
            <span>訊號價參考最大有利走勢 {{validationPct(signalValidation.signal_reference_excursion?.mfe_pct_from_signal_price)}}（最高 {{auditPrice(signalValidation.signal_reference_excursion?.max_high)}}，{{signalValidation.signal_reference_excursion?.max_high_date}}）</span>
            <span>次交易日開盤情境：{{auditPrice(signalValidation.next_trading_day_open_scenario?.entry_price)}}（{{signalValidation.next_trading_day_open_scenario?.entry_date}}） · MFE {{validationPct(signalValidation.next_trading_day_open_scenario?.mfe_pct)}} · MAE {{validationPct(signalValidation.next_trading_day_open_scenario?.mae_pct)}}</span>
            <span>假設停損：{{signalValidation.next_trading_day_open_scenario?.stop_scenario?.triggered ? '曾觸及' : '觀察期內未觸及'}} · 估算報酬 {{validationPct(signalValidation.next_trading_day_open_scenario?.stop_scenario?.gross_return_pct)}}</span>
            <pre class="gemini-review-json">{{JSON.stringify({limitations:signalValidation.not_proven, stop_scenario:signalValidation.next_trading_day_open_scenario?.stop_scenario, ground_truth_status:signalValidation.ground_truth_status, paper_orders_created:signalValidation.paper_orders_created},null,2)}}</pre>
          </template>
        </div>
        <div v-if="validationGeminiReview" class="production-import-result" :class="{failed:!validationGeminiReview.ok}">
          <b>{{validationGeminiReview.ok ? 'Gemini 事後覆核已完成' : 'Gemini 事後覆核未完成'}}</b>
          <span>{{validationGeminiReview.error || `證據 ID：${validationGeminiReview.evidence_id} · 留存：${validationGeminiReview.journal_persistence} · 原始覆核未覆寫 · 不具交易授權。`}}</span>
          <pre v-if="validationGeminiReview.review" class="gemini-review-json">{{JSON.stringify(validationGeminiReview.review,null,2)}}</pre>
        </div>
        <div v-if="decisionJournalResult" class="production-import-result" :class="{failed:!decisionJournalResult.ok}"><b>{{decisionJournalResult.ok?'決策紀錄處理完成':'決策紀錄未完成'}}</b><span>{{decisionJournalResult.error || `訊號 ${decisionJournalResult.signal_count||0} 筆 · Agent 紀錄 ${decisionJournalResult.agent_record_count||0} 筆 · 新增 ${decisionJournalResult.persisted||0} · 重複 ${decisionJournalResult.duplicates||0} · 訂單 ${decisionJournalResult.paper_orders_created??0}`}}</span></div>
        <div class="decision-journal-list"><article v-for="journal in (decisionJournal.journals||[]).slice(0,6)" :key="journal.prediction_id" class="decision-journal-card"><div class="research-result-head"><b>{{journal.symbol}} {{journal.name||''}}</b><span>{{journal.prediction_id}} · {{journal.agent_count}} Agent</span></div><div class="decision-agent-grid"><div v-for="record in journal.records" :key="record.decision_id" class="decision-agent-record"><b>{{record.agent_name}}</b><em>{{record.decision_status}}</em><p>{{record.rationale.slice(0,2).join('；')}}</p><small>證據 {{record.evidence.length}} 項 · 未知 {{record.unknowns.length}} 項</small></div></div></article><div v-if="!(decisionJournal.journals||[]).length" class="watch-empty">尚未載入決策紀錄；先按「預覽決策紀錄」。</div></div>
      </div>
    </section>

    <section id="toalpha-research" class="toalpha-research-panel">
      <div class="section-kicker"><div><span class="eyebrow">TOALPHA · STREAMABLE HTTP MCP</span><h2>AI 台股研究工具</h2></div><div class="research-head-actions"><span class="research-count">{{researchTools.length || 0}} 個可用工具</span><button class="btn-secondary" @click="loadResearchTools" :disabled="researchBusy">重新載入工具</button></div></div>
      <p class="research-intro">透過 ToAlpha 公開資料工具查詢基本面、估值、法人籌碼、財報、產業與市場結構。回傳結果會保留來源與資料日期；這裡是工具執行介面，不會把原始數據偽裝成 AI 已完成的投資結論。</p>
      <div class="research-form-grid"><label>研究工具<select v-model="researchToolName"><option v-for="tool in researchTools" :key="tool.name" :value="tool.name">{{tool.title || tool.name}}</option></select><small>{{researchToolHint(researchTools.find(t => t.name === researchToolName))}}</small></label><label>委派 Agent<select v-model="researchAgent"><option value="research">產業研究員</option><option value="quant">量化研究員</option><option value="cio">天機總指揮</option><option value="risk">風控長</option><option value="auditor">驗證員</option></select><small>工具呼叫會記錄執行 Agent 與狀態</small></label><label>股票代號／研究對象（選填）<input v-model="researchQuery" placeholder="例如：2330 或 台積電" /></label><label v-for="field in researchFields" :key="field.name">{{field.title}}<select v-if="field.enum.length" v-model="researchParams[field.name]"><option value="">請選擇</option><option v-for="choice in field.enum" :key="String(choice)" :value="choice">{{choice}}</option></select><select v-else-if="field.type === 'boolean'" v-model="researchParams[field.name]"><option value="">不指定</option><option value="true">是</option><option value="false">否</option></select><input v-else v-model="researchParams[field.name]" :type="['number','integer'].includes(field.type)?'number':'text'" :placeholder="field.required?'此欄位必填':'選填'" /><small v-if="field.description">{{field.description}}</small></label></div>
      <div class="research-actions"><button class="btn-primary" :disabled="researchBusy || !researchToolName" @click="runResearchTool">{{researchBusy ? '查詢中…' : '委派 Agent 查詢'}}</button><span class="muted">端點：toalpha.tw/mcp · 結果以研究卡片／表格呈現 · 非投資建議</span></div>
      <div v-if="researchError" class="research-error">{{researchError}}</div>
      <div v-if="researchResult" class="research-result-card"><div class="research-result-head"><b>{{researchResult.tool || researchToolName}}</b><span>{{researchResult.agent_name || researchAgentName(researchAgent)}} · {{researchResult.ok ? '查詢完成' : '已回傳結果'}}</span></div><div v-if="researchDisplay.kind === 'table'" class="research-table-wrap"><div v-if="researchDisplay.title" class="research-table-title">{{researchDisplay.title}}</div><div class="research-table-scroll"><table class="research-data-table"><thead><tr><th v-for="col in researchColumns(researchDisplay.rows)" :key="col">{{col}}</th></tr></thead><tbody><tr v-for="(row, index) in researchDisplay.rows" :key="index"><td v-for="col in researchColumns(researchDisplay.rows)" :key="col">{{researchCell(row[col])}}</td></tr></tbody></table></div><div v-if="!researchDisplay.rows.length" class="research-empty">查詢成功，但來源沒有回傳資料列。</div></div><div v-else class="research-data-cards"><article v-for="item in researchDisplay.rows" :key="item.label" class="research-data-card"><span>{{item.label}}</span><strong>{{item.value}}</strong></article></div></div>
    </section>

    <section class="control-bar"><div><span class="eyebrow">CONTROL ROOM</span><h3>研究與模擬交易控制</h3><p>自主循環預設關閉；啟動後依公開行情與風控規則運作，絕不連接實盤券商。</p></div><div class="control-actions"><button class="btn-primary" :disabled="busy||!apiOnline" @click="toggleAutonomy">{{busy?'處理中…':autonomyOn?'■ 停止自主研究':'▶ 啟動自主研究'}}</button><button class="btn-secondary" :disabled="busy||!apiOnline" @click="scanOnce">單次掃描</button><button class="btn-secondary" :disabled="busy||!apiOnline" @click="demoCycle">模擬事件測試</button><button class="btn-secondary" :disabled="!apiOnline" @click="generateReport">產生每日報告</button><button class="btn-secondary" :disabled="!apiOnline||backtestBusy||!selectedSymbol" @click="runSelectedBacktest">{{backtestBusy ? '回測中…' : '回測所選股票'}}</button></div></section>
    <section v-if="backtestReport || backtestError" class="backtest-report-panel">
      <div class="section-kicker"><div><span class="eyebrow">HISTORICAL SIMULATION</span><h2>{{backtestReport?.symbol || selectedSymbol}} 回測報告</h2></div><span class="research-count">{{backtestReport?.first_date || ''}} – {{backtestReport?.last_date || ''}}</span></div>
      <div v-if="backtestError" class="research-error">{{backtestError}}</div>
      <template v-if="backtestReport"><p class="research-intro">{{backtestReport.strategy}}</p><div class="backtest-metrics"><article><span>交易筆數</span><strong>{{backtestReport.trades}}</strong></article><article><span>勝率</span><strong>{{backtestReport.win_rate_pct}}%</strong></article><article><span>累積報酬</span><strong>{{backtestReport.total_return_pct}}%</strong></article><article><span>平均單筆報酬</span><strong>{{backtestReport.avg_return_pct}}%</strong></article><article><span>最大回撤</span><strong>{{backtestReport.max_drawdown_pct}}%</strong></article><article><span>訊號數</span><strong>{{backtestReport.signals}}</strong></article></div><div class="research-table-wrap"><div class="research-table-title">模擬交易明細</div><div class="research-table-scroll"><table class="research-data-table"><thead><tr><th>訊號日</th><th>進場日</th><th>出場日</th><th>進場價</th><th>出場價</th><th>報酬</th><th>出場原因</th></tr></thead><tbody><tr v-for="(trade, i) in backtestReport.trade_rows" :key="i"><td>{{trade.signal_date}}</td><td>{{trade.entry_date}}</td><td>{{trade.exit_date}}</td><td>{{trade.entry_price}}</td><td>{{trade.exit_price}}</td><td>{{trade.return_pct}}%</td><td>{{trade.exit_reason}}</td></tr></tbody></table><div v-if="!backtestReport.trade_rows?.length" class="research-empty">目前條件下沒有完成的模擬交易。</div></div></div><p class="research-intro">資料來源：{{backtestReport.data_source}}；資料截至：{{backtestReport.data_through}}。回測假設與限制已列入報告，尚未計入所有實務滑價及漲跌停成交限制。</p></template>
    </section>
    <div v-if="lastError" class="error-banner"><b>系統訊息</b><span>{{lastError}}</span><button @click="lastError=''">關閉</button></div>
    <footer>天機 AI QUANT LAB · ISOLATED WORKSPACE · SUPABASE-ONLY PERSISTENCE · NO LIVE ORDERS</footer>
  </main>
</template>


