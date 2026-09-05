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

const emit = defineEmits(['node-click']);
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

// 💡 邏輯一：馬卡龍色系動態色彩演算法
const getColorByHeat = (score) => {
  if (score >= 8) return '#FF9AA2'; 
  if (score >= 5) return '#FFDFBA'; 
  if (score >= 3) return '#FFD1DC'; 
  return '#AEC6CF';                 
};

// 💡 邏輯二：資料轉換層 (無外框、柔和陰影、短名稱綁定)
const formatDataToNodes = (data) => {
  return data.map(c => ({
    // 🚨 視覺降噪核心：優先使用 shortname，若無則退回 cluster_name
    name: c.shortname || c.cluster_name || c.concept_name,
    value: c.heat_score,
    symbolSize: 60 + (c.heat_score * 5),
    itemStyle: {
      color: getColorByHeat(c.heat_score),
      shadowBlur: c.heat_score >= 5 ? 15 : 0, 
      shadowColor: getColorByHeat(c.heat_score)
    },
    raw: c // 保留原始資料，供 Tooltip 與外層 Drawer 使用
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
      borderColor: '#38BDF8', // 配合科技感的藍色邊框
      borderWidth: 1,
      padding: 16,
      textStyle: { color: '#f8fafc' },
      // 🚨 深度資訊提示：Rich Tooltip 渲染
      formatter: (params) => {
        const d = params.data.raw;
        const shortName = d.shortname || d.cluster_name;
        const fullName = d.concept_name || d.cluster_name;
        const descText = d.description || '系統持續運算收集中...';

        return `
          <div style="max-width: 280px; white-space: normal; line-height: 1.6; font-family: sans-serif;">
            <div style="font-size: 16px; font-weight: bold; color: #38BDF8; margin-bottom: 2px;">
              ${shortName}
            </div>
            <div style="font-size: 12px; color: #94A3B8; margin-bottom: 10px;">
              ${fullName}
            </div>
            <div style="display: flex; gap: 16px; margin-bottom: 12px; border-bottom: 1px solid #334155; padding-bottom: 10px;">
              <span>🔥 熱度: <b style="color: #fb7185;">${d.heat_score}</b></span>
              <span>📊 量比: <b style="color: #fb923c;">${d.vol_ratio}x</b></span>
            </div>
            <div style="font-size: 12px; color: #E2E8F0; margin-bottom: 8px;">
              📌 發動標的: ${d.representative_stocks} 
            </div>
            <div style="font-size: 12px; color: #94A3B8; text-align: justify;">
              ${descText}
            </div>
          </div>
        `;
      }
    },
    series: [{
      type: 'graph',
      layout: 'force',
      force: {
        repulsion: 500,
        gravity: 0.1  
      },
      roam: true, 
      label: {
        show: true,
        formatter: '{b}',
        fontSize: 14, // 稍微縮小字級適應短名
        fontWeight: 'bold',
        color: '#ffffff', 
        textBorderColor: 'rgba(15, 23, 42, 0.8)', 
        textBorderWidth: 2,
        // 🚨 視覺降噪保護：限制寬度並在過長時顯示省略號
        overflow: 'truncate',
        width: 80
      },
      data: formatDataToNodes(props.clusterData) 
    }]
  };

  chartInstance.value.setOption(option);

  // 綁定 ECharts 點擊事件
  chartInstance.value.on('click', (params) => {
    if (params.dataType === 'node' && params.data && params.data.raw) {
      emit('node-click', params.data.raw);
    }
  });
};

watch(() => props.clusterData, (newData) => {
  if (chartInstance.value) {
    chartInstance.value.setOption({
      series: [{ data: formatDataToNodes(newData) }] 
    });
  }
}, { deep: true });

watch([width, height], () => {
  if (chartInstance.value) chartInstance.value.resize();
});

onMounted(initChart);
onUnmounted(() => {
  if (chartInstance.value) chartInstance.value.dispose();
});
</script>