&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h1 &gt;{{ title }}&lt;/h1&gt;
      &lt;p v-if="subtitle" &gt;{{ subtitle }}&lt;/p&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;slot name="actions" /&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
defineProps&lt;{
  title: string
  subtitle?: string
}&gt;()
&lt;/script&gt;
&lt;style scoped&gt;
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}
.page-title {
  font-size: 1.75rem;
  font-weight: 700;
  color: #ffffff;
  margin: 0 0 4px 0;
}
.page-subtitle {
  font-size: 1rem;
  color: rgba(255, 255, 255, 0.6);
  margin: 0;
}
@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: 16px;
  }
}
&lt;/style&gt;
&nbsp;