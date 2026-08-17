<!-- 檔案位置: tide-dashboard/src/App.vue -->
<template>
  <div class="min-h-screen bg-slate-950 p-6 md:p-10 font-sans">
    
    <!-- 頁面標題區塊 -->
    <header class="mb-8 border-b border-slate-800 pb-6">
      <div class="flex items-center space-x-4">
        <h1 class="text-3xl md:text-4xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-emerald-400 tracking-wider">
          TIDE 資金共振天機圖
        </h1>
        <span class="px-3 py-1 text-xs font-bold rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center">
          <span class="w-2 h-2 rounded-full bg-emerald-400 mr-2 animate-pulse"></span>
          盤中即時連線
        </span>
      </div>
      <p class="text-slate-400 mt-3 text-sm md:text-base">
        動態力學熱力圖：泡泡大小代表資金量能，顏色代表共振熱度，呈現真實資金推擠效應。
      </p>
    </header>

    <!-- 核心儀表板區塊 -->
    <main class="max-w-7xl mx-auto">
      <TideBubbleChart :cluster-data="mockTideData" />
    </main>
    
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import TideBubbleChart from './components/TideBubbleChart.vue';

// 初始模擬數據 (測試前端視覺用)
const mockTideData = ref([
  { cluster_name: "矽光子", heat_score: 9, vol_ratio: 3.8, representative_stocks: "3363 上詮、3163 波若威" },
  { cluster_name: "台積電建廠", heat_score: 6, vol_ratio: 2.1, representative_stocks: "2330 台積電、6187 萬潤" },
  { cluster_name: "散熱模組", heat_score: 4, vol_ratio: 1.5, representative_stocks: "3324 雙鴻、3017 奇鋐" },
  { cluster_name: "無人機", heat_score: 2, vol_ratio: 0.9, representative_stocks: "8033 雷虎" },
  { cluster_name: "光通訊", heat_score: 8, vol_ratio: 2.9, representative_stocks: "4979 華星光、3450 聯鈞" },
]);

// 模擬盤中資金灌入的動態效果 (3秒後觸發)
onMounted(() => {
  setTimeout(() => {
    mockTideData.value = [
      { cluster_name: "矽光子", heat_score: 12, vol_ratio: 5.5, representative_stocks: "3363 上詮、3163 波若威" },
      { cluster_name: "台積電建廠", heat_score: 6, vol_ratio: 2.1, representative_stocks: "2330 台積電、6187 萬潤" },
      { cluster_name: "散熱模組", heat_score: 4, vol_ratio: 1.5, representative_stocks: "3324 雙鴻、3017 奇鋐" },
      { cluster_name: "無人機", heat_score: 5, vol_ratio: 2.5, representative_stocks: "8033 雷虎" },
      { cluster_name: "光通訊", heat_score: 8, vol_ratio: 2.9, representative_stocks: "4979 華星光、3450 聯鈞" },
      { cluster_name: "CoWoS", heat_score: 9, vol_ratio: 3.2, representative_stocks: "3131 弘塑" }, 
    ];
  }, 3000);
});
</script>