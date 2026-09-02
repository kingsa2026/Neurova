# Bug Fix: Model List Not Displaying + Duplicate Model ID Prevention

**Date:** 2026-06-18
**Severity:** High (UI broken) + Medium (data integrity)
**Status:** Fixed

## Bug 1: Model List Not Displaying in Provider Cards

### Symptom

Clicking "Models" on a provider card shows an empty model list, even though models exist in the backend.

### Root Cause

`filteredModels` computed property depended on `providers.value` → `live?.models`, but `fetchModels()` replaces `providers.value` with new object references via `providers.value = providers.value.map(...)`. Vue's reactivity tracking for the nested `models` array inside each provider object was fragile — the computed dependency on `live?.models` could break when the parent array was replaced.

### Fix

Changed `filteredModels` to filter directly from `allModels.value` instead of relying on the nested `models` array inside provider objects:

```typescript
// Before (fragile)
const live = providers.value.find((p) => p.id === modelTarget.value!.id)
let list = live?.models ?? modelTarget.value.models

// After (robust)
let list = allModels.value.filter(
  (m) => m.provider_id === modelTarget.value!.id || m.provider_id === modelTarget.value!.name
)
```

## Bug 2: Duplicate Model IDs Allowed

### Symptom

Users can add the same model ID multiple times to the same provider.

### Fix

Added frontend deduplication check in `addNewModel()`:

```typescript
const exists = allModels.value.some(
  (m) => m.id === modelId && (m.provider_id === modelTarget.value!.id || m.provider_id === modelTarget.value!.name),
)
if (exists) {
  message.warning(t('model.modelAlreadyExists', { name: modelId }))
  return
}
```

## Files Changed

- `NeurUI/src/pages ModelPage.vue` — `filteredModels` rewrite + `addNewModel` dedup
- `NeurUI/src/i18n/locales/zh-CN.ts` — Added `modelAlreadyExists` key
- `NeurUI/src/i18n/locales/en-US.ts` — Added `modelAlreadyExists` key
