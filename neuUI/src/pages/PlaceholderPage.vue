&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;component :is="icon" /&gt;
      &lt;/div&gt;
      &lt;h2 &gt;{{ title }}&lt;/h2&gt;
      &lt;p &gt;{{ description }}&lt;/p&gt;
      &lt;a-tag color="blue"&gt;{{ module }}&lt;/a-tag&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  CodeOutlined,
  BuildOutlined,
  AppstoreOutlined,
} from '@ant-design/icons-vue'
const route = useRoute()
const title = computed(() =&gt; (route.meta.title as string) || '页面开发中')
const module = computed(() =&gt; (route.meta.module as string) || '')
const description = computed(() =&gt; '此页面正在开发中，敬请期待。')
const icon = computed(() =&gt; {
  const m = module.value
  if (['agents', 'chat'].includes(m)) return AppstoreOutlined
  if (['workflows', 'collaboration', 'projects'].includes(m)) return BuildOutlined
  return CodeOutlined
})
&lt;/script&gt;
&lt;style scoped&gt;
.placeholder-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 160px);
  padding: 24px;
}
.placeholder-card {
  text-align: center;
  padding: 64px 80px;
  max-width: 480px;
  width: 100%;
}
.placeholder-icon {
  font-size: 3.5rem;
  color: #60a5fa;
  margin-bottom: 20px;
  opacity: 0.7;
}
.placeholder-title {
  font-size: 1.5rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0 0 8px;
}
.placeholder-desc {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.95rem;
  margin: 0 0 16px;
}
&lt;/style&gt;
&nbsp;