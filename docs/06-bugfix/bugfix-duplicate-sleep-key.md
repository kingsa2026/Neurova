# Bug Fix: Duplicate key "sleep" in object literal

## Summary

Fixed Vite compilation warning caused by duplicate `sleep` keys in i18n language files.

## Symptoms

- Vite compilation warning: `Duplicate key "sleep" in object literal`
- Potential i18n translation conflicts due to duplicate keys

## Root Cause

In JavaScript/TypeScript object literals, duplicate keys are not allowed. When duplicate keys exist:
1. The later definition overwrites the earlier one
2. Vite/TypeScript compilers emit warnings
3. This can lead to unexpected behavior in i18n translations

## Affected Files

1. `NeurUI/src/i18n/locales/zh-CN.ts`
   - First `sleep` object: Lines 773-812 (complete sleep management translations)
   - Second `sleep` object: Lines 1418-1426 (partial translations)

2. `NeurUI/src/i18n/locales/en-US.ts`
   - First `sleep` object: Lines 743-782 (complete sleep management translations)
   - Second `sleep` object: Line 1374 (only `enabled` field)

## Fix

### zh-CN.ts

**Merged fields from second object into first object:**
- `enabled`: '启用自动休眠'
- `scheduleStart`: '休眠时间'
- `scheduleEnd`: '唤醒时间'
- `scheduleStartPlaceholder`: '选择休眠时间'
- `scheduleEndPlaceholder`: '选择唤醒时间'
- `minInterval`: '最大休眠时长'
- `hours`: '小时'

**Deleted:** Second `sleep` object (lines 1418-1426)

### en-US.ts

**Merged field from second object into first object:**
- `enabled`: 'Enable Auto Sleep'

**Deleted:** Second `sleep` object (line 1374)

## Verification

- Linter check: 0 errors for both files
- Frontend service: Successfully restarted on port 8100
- No duplicate key warnings in Vite compilation output

## Prevention

To prevent similar issues:
1. Use TypeScript interfaces/types for i18n message structures
2. Implement linting rules to detect duplicate keys
3. Use IDE features that highlight duplicate keys
4. Consider using a dedicated i18n management tool

## Related Issues

- Vite compilation warning: `Duplicate key "sleep" in object literal`
- i18n translation conflicts