<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listFiles, uploadFile, type FileItem } from '@/api/misc'

const files = ref<FileItem[]>([])
const loading = ref(true)
const error = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

function pickFile() {
  fileInput.value?.click()
}

async function onFileChosen(ev: Event) {
  const inputEl = ev.target as HTMLInputElement
  const file = inputEl.files?.[0]
  if (!file) return
  uploading.value = true
  try {
    await uploadFile(file)
    await new Promise((r) => setTimeout(r, 300))
    files.value = await listFiles()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '上传失败'
  } finally {
    uploading.value = false
    inputEl.value = ''
  }
}

onMounted(async () => {
  try {
    files.value = await listFiles()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
})

function fmtSize(n?: number): string {
  if (!n) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <div>
    <div class="head-row">
      <h2 class="page-title">文件</h2>
      <button class="ghost" :disabled="uploading" @click="pickFile">{{ uploading ? '上传中…' : '上传文件' }}</button>
      <input ref="fileInput" type="file" style="display: none" @change="onFileChosen" />
    </div>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error-text">{{ error }}</p>
    <p v-else-if="!files.length" class="muted">暂无文件</p>
    <div v-for="f in files" :key="f.file_id ?? f.name" class="card file-row">
      <div>
        <div class="file-name">{{ f.name || f.file_id }}</div>
        <div class="muted">{{ fmtSize(f.size) }}{{ f.uploaded_at ? ` · ${f.uploaded_at}` : '' }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-title { font-size: 18px; margin: 4px 0 14px; }
.head-row { display: flex; justify-content: space-between; align-items: center; }
.ghost {
  background: var(--bg-card); border: 1px solid var(--border); color: var(--primary);
  border-radius: 8px; padding: 6px 10px; font-size: 12px;
}
.file-name { font-size: 14px; margin-bottom: 2px; }
</style>
