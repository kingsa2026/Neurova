<template>
  <div class="nr-build-input">
    <template v-if="question.kind === 'secret'">
      <a-input-password
        :value="answer?.secret_value || ''"
        :placeholder="t('build.secretPlaceholder')"
        @update:value="(v: string) => update({ secret_value: v })"
      />
    </template>

    <template v-else-if="question.kind === 'multi' || question.multi">
      <a-checkbox-group
        :value="answer?.selected || []"
        class="nr-build-options"
        @update:value="(v: string[]) => update({ selected: v })"
      >
        <a-checkbox v-for="option in question.options" :key="option.label" :value="option.label">
          {{ option.label }}
          <span v-if="option.description" class="nr-build-option-desc">{{ option.description }}</span>
        </a-checkbox>
      </a-checkbox-group>
      <a-input
        v-if="question.allow_custom"
        :value="answer?.custom || ''"
        :placeholder="t('build.freeInput')"
        class="nr-build-custom"
        @update:value="(v: string) => update({ custom: v })"
      />
    </template>

    <template v-else-if="question.kind === 'choice' || question.kind === 'confirm'">
      <a-radio-group
        :value="answer?.selected?.[0] || ''"
        class="nr-build-options"
        @update:value="(v: string) => update({ selected: [v] })"
      >
        <a-radio v-for="option in question.options" :key="option.label" :value="option.label">
          {{ option.label }}
          <span v-if="option.description" class="nr-build-option-desc">{{ option.description }}</span>
        </a-radio>
      </a-radio-group>
      <a-input
        v-if="question.allow_custom"
        :value="answer?.custom || ''"
        :placeholder="t('build.freeInput')"
        class="nr-build-custom"
        @update:value="(v: string) => update({ custom: v })"
      />
    </template>

    <template v-else>
      <a-textarea
        :value="answer?.custom || ''"
        :rows="2"
        :placeholder="t('build.textPlaceholder')"
        @update:value="(v: string) => update({ custom: v })"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { BuildAnswer, BuildQuestion } from '@/api/modules/build'

const props = defineProps<{
  question: BuildQuestion
  answer?: BuildAnswer
}>()

const emit = defineEmits<{
  (e: 'change', value: BuildAnswer): void
}>()

const { t } = useI18n()

function update(patch: Partial<BuildAnswer>) {
  emit('change', {
    id: props.question.id,
    selected: patch.selected ?? props.answer?.selected ?? [],
    custom: patch.custom ?? props.answer?.custom ?? '',
    secret_value: patch.secret_value ?? props.answer?.secret_value ?? '',
  })
}
</script>

<style scoped>
.nr-build-input {
  margin-top: 8px;
}
.nr-build-options {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.nr-build-option-desc {
  margin-left: 6px;
  color: var(--nr-text-tertiary);
  font-size: 12px;
}
.nr-build-custom {
  margin-top: 6px;
}
</style>
