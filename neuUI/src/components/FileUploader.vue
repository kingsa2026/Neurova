<template>
  <div >
    <a-upload
      v-model:file-list="fileList"
      :before-upload="beforeUpload"
      :custom-request="customRequest"
      :multiple="multiple"
      :accept="accept"
    >
      <a-button >
        <UploadOutlined />
        {{ buttonText }}
      </a-button>
    </a-upload>
    <div v-if="fileList.length > 0" >
      <div
        v-for="file in fileList"
        :key="file.uid"
      >
        <FileOutlined  />
        <span >{{ file.name }}</span>
        <a-button
          type="text"
          size="small"
          @click="removeFile(file)"
        >
          <DeleteOutlined />
        </a-button>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  UploadOutlined,
  FileOutlined,
  DeleteOutlined
} from '@ant-design/icons-vue'
const props = defineProps<{
  multiple?: boolean
  accept?: string
  maxSize?: number // MB
  buttonText?: string
}>()
const emit = defineEmits<{
  (e: 'upload', file: File): void
  (e: 'remove', file: UploadFile): void
}>()
interface UploadFile {
  uid: string
  name: string
  size?: number
  type?: string
  status?: string
  url?: string
}
const fileList = ref<UploadFile[]>([])
function beforeUpload(file: File) {
  // 检查文件大小
  if (props.maxSize && file.size > props.maxSize * 1024 * 1024) {
    message.error(`文件大小不能超过 ${props.maxSize}MB`)
    return false
  }
  return true
}
interface UploadOptions {
  file: File
  onSuccess?: (body: unknown) => void
  onError?: (err: unknown) => void
}
function customRequest(options: UploadOptions) {
  const { file, onSuccess, onError } = options
  // 这里应该调用实际的 API
  // 暂时模拟上传成功
  setTimeout(() => {
    onSuccess({ url: URL.createObjectURL(file) })
    emit('upload', file)
  }, 1000)
}
function removeFile(file: UploadFile) {
  const index = fileList.value.indexOf(file)
  if (index > -1) {
    fileList.value.splice(index, 1)
    emit('remove', file)
  }
}
</script>
<style scoped>
.file-uploader {
  margin-bottom: 16px;
}
.upload-component {
  :deep(.ant-upload) {
    color: rgba(255, 255, 255, 0.8);
  }
}
.upload-btn {
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.2) !important;
  color: rgba(255, 255, 255, 0.8) !important;
  &:hover {
    border-color: #3b82f6 !important;
    color: #60a5fa !important;
  }
}
.file-list {
  margin-top: 8px;
}
.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 0.5rem;
  margin-bottom: 4px;
}
.file-icon {
  color: #60a5fa;
}
.file-name {
  flex: 1;
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.9rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.remove-btn {
  color: rgba(255, 255, 255, 0.4) !important;
  &:hover {
    color: #ef4444 !important;
  }
}
</style>
 