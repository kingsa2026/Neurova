# Bug Fix: `getPopupContainer is not a function` (Ant Design Vue v4)

**Date:** 2026-06-21
**Severity:** Medium (runtime TypeError, popup components broken)
**Status:** Fixed

## Summary

The browser console throws `TypeError: getPopupContainer is not a function` with the warning `Expected Function, got String with value "body"`. This breaks popup components (popconfirm, dropdown, tooltip, etc.) that rely on `getPopupContainer` to determine their DOM mounting parent.

## Root Cause

**Files:** `NeurUI/src/pages/AgentListPage.vue` (lines 67, 108)

### Static String Prop Instead of Function

Ant Design Vue v4's `Trigger` component requires `getPopupContainer` to be a **function** that returns an `HTMLElement`. In `AgentListPage.vue`, two `<a-popconfirm>` components had:

```vue
<a-popconfirm
  get-popup-container="body"    <!-- ❌ Static string, no ":" prefix -->
  ...
/>
```

Because the `get-popup-container` attribute lacks the Vue `:` (v-bind) prefix, Vue treats it as a **static string prop** with value `"body"`. This causes the runtime error:

```
[Vue warn]: Invalid prop: type check failed for prop "getPopupContainer".
Expected Function, got String with value "body"
```

### Why It Worked in Ant Design Vue v3

In Ant Design Vue v3, `getPopupContainer` could accept a CSS selector string like `"body"`. In v4, the API changed to require a function, aligning with Ant Design React's API.

## Fix

**File:** `NeurUI/src/pages/AgentListPage.vue`

Removed the static `get-popup-container="body"` prop from both `<a-popconfirm>` components.

### Before:

```vue
<a-popconfirm
  get-popup-container="body"          <!-- String literal → TypeError -->
  :title="t('agent.deleteConfirm')"
  @confirm="handleDelete(agent.id)"
  :ok-text="t('common.yes')"
  :cancel-text="t('common.no')"
>
  <GlassButton size="sm" variant="danger">
    {{ t('common.delete') }}
  </GlassButton>
</a-popconfirm>
```

### After:

```vue
<a-popconfirm
  :title="t('agent.deleteConfirm')"
  @confirm="handleDelete(agent.id)"
  :ok-text="t('common.yes')"
  :cancel-text="t('common.no')"
>
  <GlassButton size="sm" variant="danger">
    {{ t('common.delete') }}
  </GlassButton>
</a-popconfirm>
```

### Why This Works

The `App.vue` already wraps the entire app in `<a-config-provider>` with a proper `getPopupContainer` function:

```vue
<!-- App.vue -->
<a-config-provider :get-popup-container="getPopupContainer">
  ...
</a-config-provider>

<script setup lang="ts">
const getPopupContainer = (triggerNode?: HTMLElement) =>
  (triggerNode?.parentNode || document.body) as HTMLElement
</script>
```

Since `AgentListPage.vue` is rendered inside this ConfigProvider, all child components inherit the `getPopupContainer` function through Ant Design Vue's provide/inject context. The explicit per-component prop is unnecessary and harmful.

## Verification

1. Start the frontend: `cd NeurUI && npm run dev`
2. Open browser developer console
3. Navigate to the Agent List page
4. Verify no `getPopupContainer is not a function` error appears
5. Click the delete button on any agent card to verify the popconfirm renders correctly
6. Verify no console warnings about `getPopupContainer` prop type mismatch

## Files Changed

- `NeurUI/src/pages/AgentListPage.vue` — Removed `get-popup-container="body"` static prop from both `<a-popconfirm>` components

## Prevention

1. **Code review check**: Ensure `getPopupContainer` props are always functions (prefixed with `:`) when passing literal values
2. **Linting rule**: Add an ESLint rule to detect Ant Design Vue components with static `get-popup-container` prop
3. **TypeScript strictness**: Enable strict template type checking in Vite to catch prop type mismatches at build time
4. **Prefer ConfigProvider context**: Set `getPopupContainer` once in `App.vue`'s `<a-config-provider>` instead of per-component

## Related

- Ant Design Vue v4 migration: `getPopupContainer` changed from string/function to function-only
- Ant Design Vue v4 Trigger component now validates prop types strictly
