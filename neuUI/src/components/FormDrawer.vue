<template>
  <a-drawer
    :open="visible"
    :title="title"
    :width="width"
    @close="handleClose"
  >
    <a-form
      :model="formData"
      :layout="layout"
    >
      <slot />
    </a-form>
    <div >
      <a-button @click="handleClose">取消</a-button>
      <a-button type="primary" @click="handleSubmit" :loading="loading">
        确定
      </a-button>
    </div>
  </a-drawer>
</template>
<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{
  title: string
  width?: number
  layout?: 'horizontal' | 'vertical' | 'inline'
  loading?: boolean
}>()
const visible = ref<boolean>(false)
const formData = ref<Record<string, unknown>>({})
function open(data?: Record<string, unknown>) {
  formData.value = data || {}
  visible.value = true
}
function close() {
  visible.value = false
}
function handleClose() {
  close()
}
function handleSubmit() {
  emit('submit', formData.value)
}
const emit = defineEmits<{
  (e: 'submit', data: Record<string, unknown>): void
}>()
defineExpose({
  open,
  close
})
</script>
<style scoped>
.form-drawer {
  :deep(.ant-drawer-header) {
    background: rgba(10, 14, 39, 0.9) !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  }
  :deep(.ant-drawer-title) {
    color: #ffffff !important;
  }
  :deep(.ant-drawer-body) {
    background: rgba(10, 14, 39, 0.9) !important;
    padding: 24px;
  }
  :deep(.ant-drawer-footer) {
    background: rgba(10, 14, 39, 0.9) !important;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
  }
}
.drawer-form {
  :deep(.ant-form-item-label > label) {
    color: rgba(255, 255, 255, 0.8) !important;
  }
}
.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
 