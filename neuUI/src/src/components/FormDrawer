&lt;template&gt;
  &lt;a-drawer
    :open="visible"
    :title="title"
    :width="width"
    @close="handleClose"
  &gt;
    &lt;a-form
      :model="formData"
      :layout="layout"
    &gt;
      &lt;slot /&gt;
    &lt;/a-form&gt;
    &lt;div &gt;
      &lt;a-button @click="handleClose"&gt;取消&lt;/a-button&gt;
      &lt;a-button type="primary" @click="handleSubmit" :loading="loading"&gt;
        确定
      &lt;/a-button&gt;
    &lt;/div&gt;
  &lt;/a-drawer&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref } from 'vue'
const props = defineProps&lt;{
  title: string
  width?: number
  layout?: 'horizontal' | 'vertical' | 'inline'
  loading?: boolean
}&gt;()
const visible = ref&lt;boolean&gt;(false)
const formData = ref&lt;Record&lt;string, unknown&gt;&gt;({})
function open(data?: Record&lt;string, unknown&gt;) {
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
const emit = defineEmits&lt;{
  (e: 'submit', data: Record&lt;string, unknown&gt;): void
}&gt;()
defineExpose({
  open,
  close
})
&lt;/script&gt;
&lt;style scoped&gt;
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
  :deep(.ant-form-item-label &gt; label) {
    color: rgba(255, 255, 255, 0.8) !important;
  }
}
.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
&lt;/style&gt;
&nbsp;