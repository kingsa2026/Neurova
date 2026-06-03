&lt;template&gt;
  &lt;a-modal
    :open="visible"
    :title="title"
    :confirm-loading="loading"
    @ok="handleOk"
    @cancel="handleCancel"
  &gt;
    &lt;div &gt;
      &lt;ExclamationCircleFilled  /&gt;
      &lt;p &gt;{{ content }}&lt;/p&gt;
    &lt;/div&gt;
  &lt;/a-modal&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ExclamationCircleFilled } from '@ant-design/icons-vue'
defineProps&lt;{
  title?: string
  content: string
  loading?: boolean
}&gt;()
const visible = ref&lt;boolean&gt;(false)
function open() {
  visible.value = true
}
function close() {
  visible.value = false
}
function handleOk() {
  emit('confirm')
}
function handleCancel() {
  close()
}
const emit = defineEmits&lt;{
  (e: 'confirm'): void
}&gt;()
defineExpose({
  open,
  close
})
&lt;/script&gt;
&lt;style scoped&gt;
.confirm-modal {
  :deep(.ant-modal-header) {
    background: rgba(10, 14, 39, 0.9) !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  }
  :deep(.ant-modal-title) {
    color: #ffffff !important;
  }
  :deep(.ant-modal-body) {
    background: rgba(10, 14, 39, 0.9) !important;
    padding: 24px;
  }
  :deep(.ant-modal-footer) {
    background: rgba(10, 14, 39, 0.9) !important;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
  }
}
.modal-content {
  display: flex;
  align-items: center;
  gap: 16px;
}
.modal-icon {
  font-size: 1.5rem;
  color: #f59e0b;
}
.modal-text {
  color: rgba(255, 255, 255, 0.8);
  margin: 0;
}
&lt;/style&gt;
&nbsp;