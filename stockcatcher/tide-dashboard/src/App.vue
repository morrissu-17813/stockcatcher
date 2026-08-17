<!-- 檔案位置: tide-dashboard/src/App.vue -->
<template>
  <div class="min-h-screen bg-slate-950 p-6 md:p-10 font-sans flex flex-col relative overflow-hidden">
    
    <!-- 頁面標題區塊 -->
    <header class="mb-8 border-b border-slate-800 pb-6 shrink-0">
      <div class="flex items-center space-x-4">
        <h1 class="text-3xl md:text-4xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-emerald-400 tracking-wider">
          TIDE 資金共振天機圖
        </h1>
        <span 
          class="px-3 py-1 text-xs font-bold rounded-full border flex items-center"
          :class="statusClasses"
        >
          <span class="w-2 h-2 rounded-full mr-2" :class="statusIndicatorClasses"></span>
          {{ statusText }}
        </span>
      </div>
    </header>

    <!-- 核心儀表板區塊 -->
    <main class="max-w-7xl mx-auto w-full flex-grow relative">
      <!-- 狀態：載入中 -->
      <div v-if="isLoading" class="absolute inset-0 flex flex-col items-center justify-center z-50 bg-slate-950/80 rounded-2xl">
        <div class="w-12 h-12 border-4 border-slate-700 border-t-emerald-500 rounded-full animate-spin mb-4"></div>
        <p class="text-emerald-400 font-bold tracking-widest animate-pulse">正在擷取最新盤中數據...</p>
      </div>

      <!-- 狀態：錯誤 -->
      <div v-else-if="errorMessage" class="absolute inset-0 flex flex-col items-center justify-center z-50 bg-slate-950/80 rounded-2xl border border-rose-900/50">
        <p class="text-rose-400 font-bold text-lg mb-2">資料連線失敗</p>
        <p class="text-slate-400 text-sm max-w-md text-center">{{ errorMessage }}</p>
        <button @click="fetchTideData" class="mt-6 px-6 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg">重新嘗試</button>
      </div>

      <!-- 狀態：成功 (監聽 node-click 事件) -->
      <TideBubbleChart 
        v-else 
        :cluster-data="tideData" 
        @node-click="openDetailDrawer" 
      />
    </main>
    
    <!-- ========================================== -->
    <!-- 🌟 個股明細側邊抽屜 (Drawer UI) -->
    <!-- ========================================== -->
    
    <!-- 背景遮罩 (點擊可關閉抽屜) -->
    <div 
      v-if="selectedCluster" 
      class="fixed inset-0 bg-slate-950/60 backdrop-blur-sm z-40 transition-opacity"
      @click="closeDetailDrawer"
    ></div>

    <!-- 抽屜本體 (由右側滑入) -->
    <aside 
      class="fixed top-0 right-0 h-full w-full sm:w-[400px] bg-slate-900 border-l border-slate-800 shadow-2xl z-50 transform transition-transform duration-300 ease-out flex flex-col"
      :class="selectedCluster ? 'translate-x-0' : 'translate-x-full'"
    >
      <template v-if="selectedCluster">
        <!-- 抽屜標題 -->
        <div class="p-6 border-b border-slate-800 flex justify-between items-center bg-slate-900/50">
          <div>
            <h2 class="text-2xl font-black text-slate-100 mb-1">{{ selectedCluster.cluster_name }}</h2>
            <div class="flex space-x-3 text-sm">
              <span class="text-rose-400">🔥 熱度: {{ selectedCluster.heat_score }}</span>
              <span class="text-amber-400">📊 量比: {{ selectedCluster.vol_ratio }}x</span>
            </div>
          </div>
          <button @click="closeDetailDrawer" class="text-slate-400 hover:text-white transition-colors p-2 rounded-full hover:bg-slate-800">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
          </button>
        </div>

        <!-- 抽屜內容 (個股明細清單) -->
        <div class="flex-grow overflow-y-auto p-4 space-y-3">
          <div 
            v-for="stock in selectedCluster.stocks_detail" 
            :key="stock.sid"
            class="bg-slate-800/50 rounded-xl p-4 border border-slate-700/50 hover:border-slate-600 transition-colors flex justify-between items-center"
          >
            <!-- 股票代號與名稱 -->
            <div class="flex flex-col">
              <span class="text-xs text-slate-400 font-mono">{{ stock.sid }}</span>
              <span class="text-lg font-bold text-slate-200">{{ stock.name }}</span>
            </div>
            
            <!-- 漲跌幅與量能比 -->
            <div class="flex flex-col items-end text-right">
              <!-- 依據漲跌幅顯示紅色或綠色 (台股習慣：紅漲綠跌) -->
              <span 
                class="font-black text-lg"
                :class="stock.pct >= 0 ? 'text-rose-500' : 'text-emerald-500'"
              >
                {{ stock.pct > 0 ? '+' : '' }}{{ stock.pct }}%
              </span>
              <span class="text-xs text-slate-400 mt-1">量比 {{ stock.vol_ratio }}x</span>
            </div>
          </div>
        </div>
      </template>
    </aside>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import TideBubbleChart from './components/TideBubbleChart.vue';

// 資料與狀態
const tideData = ref([]);
const isLoading = ref(true);
const errorMessage = ref('');
const selectedCluster = ref(null); // 控制抽屜的狀態與資料

// 開關抽屜的方法
const openDetailDrawer = (clusterInfo) => {
  selectedCluster.value = clusterInfo;
};
const closeDetailDrawer = () => {
  selectedCluster.value = null;
};

// 狀態樣式動態計算
const statusClasses = computed(() => {
  if (isLoading.value) return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
  if (errorMessage.value) return 'bg-rose-500/20 text-rose-400 border-rose-500/30';
  return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
});
const statusIndicatorClasses = computed(() => {
  if (isLoading.value) return 'bg-amber-400 animate-bounce';
  if (errorMessage.value) return 'bg-rose-400';
  return 'bg-emerald-400 animate-pulse';
});
const statusText = computed(() => {
  if (isLoading.value) return '資料同步中...';
  if (errorMessage.value) return '連線中斷';
  return '盤中即時連線';
});

// 擷取 API 邏輯
const fetchTideData = async () => {
  isLoading.value = true;
  errorMessage.value = '';
  try {
    const baseUrl =  "https://stockcatcher-jet.vercel.app";
    if (!baseUrl) throw new Error('系統未設定後端 API 網址');

    const response = await fetch(`${baseUrl}/api/tide`, { method: 'GET', headers: { 'Accept': 'application/json' } });
    if (!response.ok) throw new Error(`伺服器回應錯誤 (HTTP ${response.status})`);

    const result = await response.json();
    if (result.status === 'success' && Array.isArray(result.data)) {
      tideData.value = result.data;
    } else {
      throw new Error('後端回傳的資料格式不符預期');
    }
  } catch (error) {
    console.error('❌ [API Fetch Error]:', error);
    errorMessage.value = error.message;
  } finally {
    isLoading.value = false;
  }
};

onMounted(fetchTideData);
</script>