<template>
  <div class="validation-result">
    <div class="result-header">
      <div class="result-status" :class="{ valid: result.valid, invalid: !result.valid }">
        <check-circle-outlined v-if="result.valid" />
        <close-circle-outlined v-else />
        <span>{{ result.valid ? '验证通过' : '验证失败' }}</span>
      </div>
      <div class="result-summary">
        <span v-if="result.errors.length > 0" class="error-count">
          {{ result.errors.length }} 个错误
        </span>
        <span v-if="result.warnings.length > 0" class="warning-count">
          {{ result.warnings.length }} 个警告
        </span>
      </div>
    </div>

    <div v-if="result.errors.length > 0" class="errors-section">
      <div class="section-title">
        <close-circle-outlined />
        错误
      </div>
      <div class="issue-list">
        <div
          v-for="(error, index) in result.errors"
          :key="index"
          class="issue-item error"
        >
          <div class="issue-icon">
            <close-circle-outlined />
          </div>
          <div class="issue-content">
            <div class="issue-message">{{ error.message }}</div>
            <div class="issue-details">
              <span v-if="error.nodeId" class="detail-tag">节点: {{ error.nodeId }}</span>
              <span v-if="error.edgeId" class="detail-tag">边: {{ error.edgeId }}</span>
              <span v-if="error.field" class="detail-tag">字段: {{ error.field }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="result.warnings.length > 0" class="warnings-section">
      <div class="section-title">
        <warning-outlined />
        警告
      </div>
      <div class="issue-list">
        <div
          v-for="(warning, index) in result.warnings"
          :key="index"
          class="issue-item warning"
        >
          <div class="issue-icon">
            <warning-outlined />
          </div>
          <div class="issue-content">
            <div class="issue-message">{{ warning.message }}</div>
            <div class="issue-details">
              <span v-if="warning.nodeId" class="detail-tag">节点: {{ warning.nodeId }}</span>
              <span v-if="warning.edgeId" class="detail-tag">边: {{ warning.edgeId }}</span>
              <span v-if="warning.field" class="detail-tag">字段: {{ warning.field }}</span>
            </div>
            <div v-if="warning.suggestion" class="issue-suggestion">
              <info-circle-outlined />
              {{ warning.suggestion }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="result.valid && result.errors.length === 0 && result.warnings.length === 0" class="no-issues">
      <check-circle-outlined />
      <span>没有发现问题</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { CheckCircleOutlined, CloseCircleOutlined, WarningOutlined, InfoCircleOutlined } from '@ant-design/icons-vue'
import type { ValidationResult } from '../types'

interface Props {
  result: ValidationResult
}

defineProps<Props>()
</script>

<style scoped>
.validation-result {
  max-height: 400px;
  overflow-y: auto;
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e8e8e8;
}

.result-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 500;
}

.result-status.valid {
  color: #52c41a;
}

.result-status.invalid {
  color: #ff4d4f;
}

.result-summary {
  display: flex;
  gap: 12px;
}

.error-count {
  color: #ff4d4f;
  font-weight: 500;
}

.warning-count {
  color: #faad14;
  font-weight: 500;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-weight: 500;
  font-size: 14px;
}

.errors-section .section-title {
  color: #ff4d4f;
}

.warnings-section .section-title {
  color: #faad14;
}

.issue-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.issue-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  border-radius: 6px;
  border: 1px solid;
}

.issue-item.error {
  background: #fff2f0;
  border-color: #ffccc7;
}

.issue-item.warning {
  background: #fffbe6;
  border-color: #ffe58f;
}

.issue-icon {
  font-size: 16px;
  margin-top: 2px;
}

.issue-item.error .issue-icon {
  color: #ff4d4f;
}

.issue-item.warning .issue-icon {
  color: #faad14;
}

.issue-content {
  flex: 1;
}

.issue-message {
  margin-bottom: 8px;
  line-height: 1.5;
}

.issue-details {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.detail-tag {
  font-size: 12px;
  padding: 2px 8px;
  background: rgba(0, 0, 0, 0.06);
  border-radius: 4px;
  color: #666;
}

.issue-suggestion {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  color: #666;
  padding: 8px;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 4px;
}

.no-issues {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: #52c41a;
  font-size: 14px;
}
</style>