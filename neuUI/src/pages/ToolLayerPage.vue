<template>
  <div >
    <div >
      <h2 >
        <ToolOutlined :style="{ color: '#f59e0b' }" /> 工具层管理
      </h2>
    </div>
    <div >
      <div >工具层<b >{{ list.length }}</b></div>
      <div >工具<b >{{ totalTools }}</b></div>
    </div>
    <div >
      <a-table :columns="cols" :data-source="list" row-key="id" size="middle" :pagination="false">
        <template #bodyCell="{ column: c, record: r }">
          <template v-if="c.key === 'st'">
            <a-switch v-model:checked="r.on" size="small" />
          </template>
        </template>
      </a-table>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed } from 'vue'
import { ToolOutlined } from '@ant-design/icons-vue'
const cols = [
  { title: '名称', dataIndex: 'name' },
  { title: '描述', dataIndex: 'desc' },
  { title: '工具数', dataIndex: 'cnt', width: 80 },
  { title: '状态', key: 'st', width: 70 },
]
const list = ref([
  { id: '1', name: '文件操作层', desc: '文件读写、上传下载', cnt: 8, on: true },
  { id: '2', name: 'API调用层', desc: '第三方API集成', cnt: 12, on: true },
  { id: '3', name: '数据库层', desc: 'SQL/NoSQL操作', cnt: 6, on: true },
  { id: '4', name: '搜索层', desc: '向量搜索、全文检索', cnt: 5, on: true },
  { id: '5', name: '代码执行层', desc: '沙箱代码运行', cnt: 4, on: false },
  { id: '6', name: '媒体处理层', desc: '图片/音频/视频处理', cnt: 7, on: true },
  { id: '7', name: '网络层', desc: 'HTTP/WebSocket通信', cnt: 9, on: true },
  { id: '8', name: '数据转换层', desc: '格式转换、编码解码', cnt: 5, on: false },
])
const totalTools = computed(() => list.value.reduce((sum, item) => sum + item.cnt, 0))
</script>
<style scoped>
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.sr { display: flex; gap: 12px; }
.s { flex: 1; padding: 14px 18px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; color: rgba(255,255,255,0.5); font-size: .85rem; }
.s b { font-size: 1.4rem; }
.c1 { color: #f59e0b; }
.tb { padding: 20px; border-radius: 12px; }
</style>
 