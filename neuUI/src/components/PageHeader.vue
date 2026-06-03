<template>
  <div >
    <div >
      <h1 >{{ title }}</h1>
      <p v-if="subtitle" >{{ subtitle }}</p>
    </div>
    <div >
      <slot name="actions" />
    </div>
  </div>
</template>
<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>
<style scoped>
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
</style>
 