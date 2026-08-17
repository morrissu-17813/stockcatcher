<!-- 檔案位置: tide-dashboard/src/components/TideBubbleChart.vue -->
<template>
  <div class="relative w-full h-[650px] bg-slate-900 rounded-2xl border border-slate-800 shadow-2xl overflow-hidden p-4">
    <!-- ECharts 畫布 -->
    <div ref="chartRef" class="w-full h-full z-10 relative"></div>
    
    <!-- 科技感背光暈 -->
    <div class="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-blue-900/10 via-transparent to-transparent pointer-events-none z-0"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, shallowRef } from 'vue';
import * as echarts from 'echarts';
import { useElementSize } from '@vueuse/core';

const props = defineProps({
  clusterData: {
    type: Array,
    required: true,
    default: () => []
  }
});

const chartRef = ref(null);
const chartInstance = shallowRef(null);
const { width, height } = useElementSize(chartRef);

// 💡 邏輯一：馬卡龍色系動態色彩演算法 (符合人類物理直覺的溫度映射)
const getColorByHeat = (score) => {
  if (score >= 8) return '#FF9AA2'; // 🍓 馬卡龍草莓紅：極度狂熱、資金高度集中推擠
  if (score >= 5) return '#FFDFBA'; // 🍊 馬卡龍蜜桃橘：熱度升溫、動能明顯轉強
  if (score >= 3) return '#FFD1DC'; // 🌸 粉嫩櫻花粉：溫和發酵、資金初步進駐
  return '#AEC6CF';                 // ☁️ 霧面天空藍：冷靜、常溫狀態
};

// 💡 邏輯二：資料轉換層 (無外框、柔和陰影)
const formatDataToNodes = (data) => {
  return data.map(c => ({
    name: c.cluster_name,
    value: c.heat_score,
    symbolSize: 60 + (c.heat_score * 5), // 氣泡大小由熱度決定
    itemStyle: {
      color: getColorByHeat(c.heat_score),
      // 拔除 borderColor 與 borderWidth，讓邊緣變柔和
      shadowBlur: c.heat_score >= 5 ? 15 : 0, 
      shadowColor: getColorByHeat(c.heat_score)
    },
    raw: c // 保留原始資料，供 Tooltip 與未來點擊顯示明細使用
  }));
};

// 初始化圖表實體
const initChart = () => {
  if (!chartRef.value) return;
  chartInstance.value = echarts.init(chartRef.value, 'dark');

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(15, 23, 42, 0.95)',
      borderColor: '#334155',
      textStyle: { color: '#f8fafc' },
      formatter: (params) => {
        const d = params.data.raw;
        return `
          <div style="font-weight:bold; font-size:16px; margin-bottom:8px; border-bottom:1px solid #334155; padding-bottom:4px;">${d.cluster_name}</div>
          <div>🔥 熱度：<span style="color:#fb7185; font-weight:bold;">${d.heat_score}</span></div>
          <div>📊 量比：<span style="color:#fb923c; font-weight:bold;">${d.vol_ratio}x</span></div>
          <div style="margin-top:8px; font-size:12px; color:#94a3b8; max-width:200px; white-space:normal;">
            領漲標的：${d.representative_stocks}
          </div>
        `;
      }
    },
    series: [{
      type: 'graph',
      layout: 'force',
      force: {
        repulsion: 500, // 推擠排斥力
        gravity: 0.1    // 向心引力
      },
      roam: true, // 允許滑鼠滾輪縮放與拖曳
      label: {
        show: true,
        formatter: '{b}',
        fontSize: 16,
        fontWeight: 'bold',
        color: '#ffffff', // 保持純白字體
        textBorderColor: 'rgba(15, 23, 42, 0.8)', // 描邊確保白字在高明度泡泡上清晰
        textBorderWidth: 2
      },
      data: formatDataToNodes(props.clusterData) 
    }]
  };

  chartInstance.value.setOption(option);
};

// 監聽資料變化，動態更新圖表 (ECharts 會自動平滑動畫)
watch(() => props.clusterData, (newData) => {
  if (chartInstance.value) {
    chartInstance.value.setOption({
      series: [{ data: formatDataToNodes(newData) }] 
    });
  }
}, { deep: true });
//TTT
// 視窗 RWD 縮放監聽
watch([width, height], () => {
  if (chartInstance.value) chartInstance.value.resize();
});

onMounted(initChart);
onUnmounted(() => {
  if (chartInstance.value) chartInstance.value.dispose();
});
</script>