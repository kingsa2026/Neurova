<template>
  <div class="stat-card glass-effect">
    <div class="stat-icon" :style="{ background: color + '20', color: color }">
      {{ prefix }}
    </div>
    <div class="stat-info">
      <div class="stat-title">{{ title }}</div>
      <div class="stat-value" :style="{ color: color }">{{ value }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  value: number
  prefix: string
  color: string
}>()
</script>

<style scoped>
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
</style>
