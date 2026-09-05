&lt;template&gt;
  &lt;div &gt;
    &lt;a-upload
      v-model:file-list="fileList"
      :before-upload="beforeUpload"
      :custom-request="customRequest"
      :multiple="multiple"
      :accept="accept"
    &gt;
      &lt;a-button &gt;
        &lt;UploadOutlined /&gt;
        {{ buttonText }}
      &lt;/a-button&gt;
    &lt;/a-upload&gt;
    &lt;div v-if="fileList.length &gt; 0" &gt;
      &lt;div
        v-for="file in fileList"
        :key="file.uid"
      &gt;
        &lt;FileOutlined  /&gt;
        &lt;span &gt;{{ file.name }}&lt;/span&gt;
        &lt;a-button
          type="text"
          size="small"
          @click="removeFile(file)"
        &gt;
          &lt;DeleteOutlined /&gt;
        &lt;/a-button&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  UploadOutlined,
  FileOutlined,
  DeleteOutlined
} from '@ant-design/icons-vue'
const props = defineProps&lt;{
  multiple?: boolean
  accept?: string
  maxSize?: number // MB
  buttonText?: string
}&gt;()
const emit = defineEmits&lt;{
  (e: 'upload', file: File): void
  (e: 'remove', file: UploadFile): void
}&gt;()
interface UploadFile {
  uid: string
  name: string
  size?: number
  type?: string
  status?: string
  url?: string
}
const fileList = ref&lt;UploadFile[]&gt;([])
function beforeUpload(file: File) {
  // 检查文件大小
  if (props.maxSize &amp;&amp; file.size &gt; props.maxSize * 1024 * 1024) {
    message.error(`文件大小不能超过 ${props.maxSize}MB`)
    return false
  }
  return true
}
interface UploadOptions {
  file: File
  onSuccess?: (body: unknown) =&gt; void
  onError?: (err: unknown) =&gt; void
}
function customRequest(options: UploadOptions) {
  const { file, onSuccess, onError } = options
  // 这里应该调用实际的 API
  // 暂时模拟上传成功
  setTimeout(() =&gt; {
    onSuccess({ url: URL.createObjectURL(file) })
    emit('upload', file)
  }, 1000)
}
function removeFile(file: UploadFile) {
  const index = fileList.value.indexOf(file)
  if (index &gt; -1) {
    fileList.value.splice(index, 1)
    emit('remove', file)
  }
}
&lt;/script&gt;
&lt;style scoped&gt;
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
  &amp;:hover {
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
  &amp;:hover {
    color: #ef4444 !important;
  }
}
&lt;/style&gt;
&nbsp;