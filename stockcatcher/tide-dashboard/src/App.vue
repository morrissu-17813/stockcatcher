<!-- 檔案位置: tide-dashboard/src/App.vue -->
<template>
  <div class="min-h-screen bg-slate-950 p-6 md:p-10 font-sans flex flex-col">
    
    <!-- 頁面標題區塊 -->
    <header class="mb-8 border-b border-slate-800 pb-6 shrink-0">
      <div class="flex items-center space-x-4">
        <h1 class="text-3xl md:text-4xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-emerald-400 tracking-wider">
          TIDE 資金共振天機圖
        </h1>
        <!-- 動態狀態標籤：根據連線狀態切換顏色與文字 -->
        <span 
          class="px-3 py-1 text-xs font-bold rounded-full border flex items-center"
          :class="{
            'bg-emerald-500/20 text-emerald-400 border-emerald-500/30': !isLoading && !errorMessage,
            'bg-amber-500/20 text-amber-400 border-amber-500/30': isLoading,
            'bg-rose-500/20 text-rose-400 border-rose-500/30': errorMessage
          }"
        >
          <span 
            class="w-2 h-2 rounded-full mr-2"
            :class="{
              'bg-emerald-400 animate-pulse': !isLoading && !errorMessage,
              'bg-amber-400 animate-bounce': isLoading,
              'bg-rose-400': errorMessage
            }"
          ></span>
          {{ statusText }}
        </span>
      </div>
      <p class="text-slate-400 mt-3 text-sm md:text-base">
        動態力學熱力圖：泡泡大小代表資金量能，顏色代表共振熱度，呈現真實資金推擠效應。
      </p>
    </header>

    <!-- 核心儀表板區塊 -->
    <main class="max-w-7xl mx-auto w-full flex-grow relative">
      <!-- 狀態：載入中 -->
      <div v-if="isLoading" class="absolute inset-0 flex flex-col items-center justify-center z-50 bg-slate-950/80 rounded-2xl">
        <div class="w-12 h-12 border-4 border-slate-700 border-t-emerald-500 rounded-full animate-spin mb-4"></div>
        <p class="text-emerald-400 font-bold tracking-widest animate-pulse">正在擷取最新盤中數據...</p>
      </div>

      <!-- 狀態：發生錯誤 -->
      <div v-else-if="errorMessage" class="absolute inset-0 flex flex-col items-center justify-center z-50 bg-slate-950/80 rounded-2xl border border-rose-900/50">
        <svg class="w-16 h-16 text-rose-500 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
        <p class="text-rose-400 font-bold text-lg mb-2">資料連線失敗</p>
        <p class="text-slate-400 text-sm max-w-md text-center">{{ errorMessage }}</p>
        <button @click="fetchTideData" class="mt-6 px-6 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition-colors border border-slate-700">
          重新嘗試
        </button>
      </div>

      <!-- 狀態：資料載入成功 (掛載泡泡圖元件) -->
      <TideBubbleChart v-else :cluster-data="tideData" />
    </main>
    
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import TideBubbleChart from './components/TideBubbleChart.vue';

// 狀態管理 (State Management)
const tideData = ref([]);
const isLoading = ref(true);
const errorMessage = ref('');

// 動態計算連線狀態文字
const statusText = computed(() => {
  if (isLoading.value) return '資料同步中...';
  if (errorMessage.value) return '連線中斷';
  return '盤中即時連線';
});

// 負責向後端 API 請求資料的核心函式
const fetchTideData = async () => {
  isLoading.value = true;
  errorMessage.value = '';
  
  try {
    // 💡 最佳實踐：從環境變數讀取後端 URL，避免將網址硬編碼在原始碼中
    // 本地開發時由 Vite 注入，Vercel 部署時由 Dashboard 設定注入
    const baseUrl = "https://tide-dashboard-ebon.vercel.app"//import.meta.env.VITE_API_BASE_URL;
    
    if (!baseUrl) {
      throw new Error('系統未設定後端 API 網址 (VITE_API_BASE_URL 遺失)');
    }

    // 發起 API 請求
    const response = await fetch(`${baseUrl}/api/tide`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      }
    });

    if (!response.ok) {
      throw new Error(`伺服器回應錯誤 (HTTP ${response.status})`);
    }

    const result = await response.json();

    // 驗證 API 回傳格式是否符合預期
    if (result.status === 'success' && Array.isArray(result.data)) {
      tideData.value = result.data;
    } else {
      throw new Error('後端回傳的資料格式不符預期');
    }

  } catch (error) {
    console.error('❌ [API Fetch Error]:', error);
    errorMessage.value = error.message || '無法連線至伺服器，請確認網路或後端狀態。';
  } finally {
    // 確保無論成功或失敗，都會關閉載入動畫，避免使用者卡死
    isLoading.value = false;
  }
};

// 元件掛載完成後，立即觸發資料擷取
onMounted(() => {
  fetchTideData();
});
</script>