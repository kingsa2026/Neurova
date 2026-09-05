&lt;template&gt;
  &lt;div &gt;
    &lt;div  :style="{ background: color + '20', color: color }"&gt;
      {{ prefix }}
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;{{ title }}&lt;/div&gt;
      &lt;div  :style="{ color: color }"&gt;{{ value }}&lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
defineProps&lt;{
  title: string
  value: number
  prefix: string
  color: string
}&gt;()
&lt;/script&gt;
&lt;style scoped&gt;
.stat-card {
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
}
.stat-info {
  flex: 1;
}
.stat-title {
  font-size: 0.9rem;
  color: rgba(255, 255, 255, 0.6);
  margin-bottom: 4px;
}
.stat-value {
  font-size: 2rem;
  font-weight: 700;
}
&lt;/style&gt;
&nbsp;