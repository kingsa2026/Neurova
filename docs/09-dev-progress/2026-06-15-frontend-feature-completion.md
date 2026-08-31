# Frontend Page Feature Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 83 missing UI features across 26 pages — error handling, delete confirmations, form validation, pagination, empty states, and loading states.

**Architecture:** Each page is modified independently. Changes are surgical: add `message.error()` to empty catch blocks, wrap delete buttons in `a-popconfirm`, add `rules` props to forms, add `a-pagination` to lists, add `a-empty` to tables, add `a-spin` loading wrappers. No new files needed — all changes are within existing `.vue` files.

**Tech Stack:** Vue 3, Ant Design Vue (a-popconfirm, a-empty, a-pagination, a-spin, message), TypeScript

---

## Phase 1: Error Handling + Delete Confirmation (42 issues)

These are the highest priority — silent errors hide bugs, missing confirmations risk data loss.

### Task 1: WebhookPage.vue — Error handling

**Files:** `NeurUI/src/pages/WebhookPage.vue`

- [ ] **Step 1:** Replace all 5 empty `catch {}` blocks with `message.error(t('common.error'))` calls. Lines 163, 179, 186, 193, 208.

- [ ] **Step 2:** Run `npx vitest run` to verify no regressions.

### Task 2: TaskPage.vue — Error handling

**Files:** `NeurUI/src/pages/TaskPage.vue`

- [ ] **Step 1:** Replace empty catch blocks at lines 172, 181, 191, 198 with `message.error(t('common.error'))`.

- [ ] **Step 2:** Run tests.

### Task 3: AgentSchedulerPage.vue — Error handling

**Files:** `NeurUI/src/pages/AgentSchedulerPage.vue`

- [ ] **Step 1:** Replace empty catch blocks at lines 160, 187, 194, 207 with `message.error(t('common.error'))`.

- [ ] **Step 2:** Run tests.

### Task 4: ProjectPage.vue — Error handling

**Files:** `NeurUI/src/pages/ProjectPage.vue`

- [ ] **Step 1:** Replace empty catch blocks at lines 139, 154, 161 with `message.error(t('common.error'))`.

- [ ] **Step 2:** Run tests.

### Task 5: AgentChannelPage.vue — Error handling

**Files:** `NeurUI/src/pages/AgentChannelPage.vue`

- [ ] **Step 1:** Replace empty catch blocks at lines 121, 136, 143, 150, 157 with `message.error(t('common.error'))`.

- [ ] **Step 2:** Run tests.

### Task 6: AgentRulePage.vue — Error handling

**Files:** `NeurUI/src/pages/AgentRulePage.vue`

- [ ] **Step 1:** Replace empty catch blocks at lines 158, 173, 180, 187, 194 with `message.error(t('common.error'))`.

- [ ] **Step 2:** Run tests.

### Task 7: TeamPage.vue — Error handling

**Files:** `NeurUI/src/pages/TeamPage.vue`

- [ ] **Step 1:** Replace empty catch blocks at lines 118, 133, 140, 153 with `message.error(t('common.error'))`.

- [ ] **Step 2:** Run tests.

### Task 8: ModelPage.vue — Error handling + delete confirm

**Files:** `NeurUI/src/pages/ModelPage.vue`

- [ ] **Step 1:** Replace silent catch blocks at lines 527, 548-549, 560-562 with `message.error()`.

- [ ] **Step 2:** Fix line 878-880: move `message.success` inside the `try` block so it only shows on actual success. Add `message.error` in catch.

- [ ] **Step 3:** Wrap `deleteProvider` button (line 138) and `deleteModel` button (line 310) in `a-popconfirm`.

- [ ] **Step 4:** Run tests.

### Task 9: NotificationPage.vue — Delete confirm

**Files:** `NeurUI/src/pages/NotificationPage.vue`

- [ ] **Step 1:** Wrap delete button (line 36-38) in `a-popconfirm`.

- [ ] **Step 2:** Run tests.

### Task 10: LogPage.vue — Clear confirm

**Files:** `NeurUI/src/pages/LogPage.vue`

- [ ] **Step 1:** Wrap clear logs button (line 7) in `a-popconfirm` with warning text.

- [ ] **Step 2:** Run tests.

### Task 11: ToolLayerPage.vue — Unregister confirm

**Files:** `NeurUI/src/pages/ToolLayerPage.vue`

- [ ] **Step 1:** Wrap `unregisterServer` button (line 34-35) in `a-popconfirm`.

- [ ] **Step 2:** Run tests.

### Task 12: GroupPage.vue — Remove member confirm

**Files:** `NeurUI/src/pages/GroupPage.vue`

- [ ] **Step 1:** Wrap `removeMember` button (line 169-177) in `a-popconfirm`.

- [ ] **Step 2:** Run tests.

### Task 13: ChannelIntegrationPage.vue — Error handling

**Files:** `NeurUI/src/pages/ChannelIntegrationPage.vue`

- [ ] **Step 1:** Replace `console.warn` at line 431-433 with `message.error(t('common.error'))`.

- [ ] **Step 2:** Run tests.

---

## Phase 2: Form Validation (16 issues)

Add `rules` prop to forms for inline validation feedback.

### Task 14: WebhookPage.vue — Form validation

**Files:** `NeurUI/src/pages/WebhookPage.vue`

- [ ] **Step 1:** Add `rules` prop to the `a-form` at line 40: `{ url: [{ required: true, message: t('common.required') }], events: [{ required: true, message: t('common.required') }] }`. Remove manual `if (!form.url) return` check.

- [ ] **Step 2:** Run tests.

### Task 15: TaskPage.vue — Form validation

**Files:** `NeurUI/src/pages/TaskPage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 74: `{ title: [{ required: true, message: t('common.required') }] }`. Remove manual check.

- [ ] **Step 2:** Run tests.

### Task 16: AgentSchedulerPage.vue — Form validation

**Files:** `NeurUI/src/pages/AgentSchedulerPage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 46: `{ name: [{ required: true, message: t('common.required') }] }`. Remove manual check.

- [ ] **Step 2:** Run tests.

### Task 17: ProjectPage.vue — Form validation

**Files:** `NeurUI/src/pages/ProjectPage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 64: `{ name: [{ required: true, message: t('common.required') }] }`. Remove manual check.

- [ ] **Step 2:** Run tests.

### Task 18: GroupPage.vue — Form validation

**Files:** `NeurUI/src/pages/GroupPage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 33: `{ name: [{ required: true, message: t('common.required') }] }`.

- [ ] **Step 2:** Run tests.

### Task 19: ToolLayerPage.vue — Form validation

**Files:** `NeurUI/src/pages/ToolLayerPage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 81: `{ name: [{ required: true }], url: [{ required: true }, { type: 'url', message: 'Invalid URL' }] }`.

- [ ] **Step 2:** Run tests.

### Task 20: AgentChannelPage.vue — Form validation

**Files:** `NeurUI/src/pages/AgentChannelPage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 38: `{ name: [{ required: true }] }`. Remove manual check.

- [ ] **Step 2:** Run tests.

### Task 21: AgentRulePage.vue — Form validation

**Files:** `NeurUI/src/pages/AgentRulePage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 40: `{ name: [{ required: true }] }`. Remove manual check.

- [ ] **Step 2:** Run tests.

### Task 22: TeamPage.vue — Form validation

**Files:** `NeurUI/src/pages/TeamPage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 39: `{ name: [{ required: true }] }`. Remove manual check.

- [ ] **Step 2:** Run tests.

### Task 23: MemoryPage.vue — Form validation

**Files:** `NeurUI/src/pages/MemoryPage.vue`

- [ ] **Step 1:** Add `rules` prop to create modal form at line 232: `{ content: [{ required: true }] }`. Remove manual check.

- [ ] **Step 2:** Run tests.

### Task 24: KnowledgePage.vue — Form validation

**Files:** `NeurUI/src/pages/KnowledgePage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 85: `{ title: [{ required: true }] }`. Remove manual check.

- [ ] **Step 2:** Run tests.

### Task 25: SkillPoolPage.vue — Form validation

**Files:** `NeurUI/src/pages/SkillPoolPage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 109. Remove manual check.

- [ ] **Step 2:** Run tests.

### Task 26: AgentFormPage.vue — Form validation

**Files:** `NeurUI/src/pages/AgentFormPage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 14: `{ name: [{ required: true }] }`. Remove manual check.

- [ ] **Step 2:** Run tests.

### Task 27: SettingPage.vue — Form validation

**Files:** `NeurUI/src/pages/SettingPage.vue`

- [ ] **Step 1:** Add `rules` props to all 5 settings forms (general, llm, security, storage, advanced) with appropriate required fields.

- [ ] **Step 2:** Run tests.

### Task 28: FirewallPage.vue — Form validation

**Files:** `NeurUI/src/pages/FirewallPage.vue`

- [ ] **Step 1:** Add `rules` prop to form at line 99: `{ name: [{ required: true }], pattern: [{ required: true }] }`.

- [ ] **Step 2:** Run tests.

---

## Phase 3: Pagination (15 issues)

Add `a-pagination` to list pages that render all items at once.

### Task 29: AgentListPage.vue — Card view pagination

**Files:** `NeurUI/src/pages/AgentListPage.vue`

- [ ] **Step 1:** Add `a-pagination` below card grid (after line 79). Add `currentPage` and `pageSize` refs. Slice `filteredAgents` for card view.

- [ ] **Step 2:** Run tests.

### Task 30: NotificationPage.vue — List pagination

**Files:** `NeurUI/src/pages/NotificationPage.vue`

- [ ] **Step 1:** Add `a-pagination` component. Wire to existing `total`/`pageSize` refs. Slice notifications for display.

- [ ] **Step 2:** Run tests.

### Task 31: AgentMediaPage.vue — Grid pagination

**Files:** `NeurUI/src/pages/AgentMediaPage.vue`

- [ ] **Step 1:** Add `a-pagination` below grid. Add pagination state refs.

- [ ] **Step 2:** Run tests.

### Task 32: SkillPoolPage.vue — Grid pagination

**Files:** `NeurUI/src/pages/SkillPoolPage.vue`

- [ ] **Step 1:** Add `a-pagination` below both public and private skill grids.

- [ ] **Step 2:** Run tests.

### Task 33: GroupPage.vue — Grid pagination

**Files:** `NeurUI/src/pages/GroupPage.vue`

- [ ] **Step 1:** Add `a-pagination` below groups grid.

- [ ] **Step 2:** Run tests.

### Task 34: TeamPage.vue — Grid pagination

**Files:** `NeurUI/src/pages/TeamPage.vue`

- [ ] **Step 1:** Add `a-pagination` below teams grid.

- [ ] **Step 2:** Run tests.

### Task 35: ProjectPage.vue — Grid pagination

**Files:** `NeurUI/src/pages/ProjectPage.vue`

- [ ] **Step 1:** Add `a-pagination` below projects grid.

- [ ] **Step 2:** Run tests.

### Task 36: AgentChannelPage.vue — Grid pagination

**Files:** `NeurUI/src/pages/AgentChannelPage.vue`

- [ ] **Step 1:** Add `a-pagination` below channel list grid.

- [ ] **Step 2:** Run tests.

### Task 37: AgentRulePage.vue — List pagination

**Files:** `NeurUI/src/pages/AgentRulePage.vue`

- [ ] **Step 1:** Add `a-pagination` below rule list.

- [ ] **Step 2:** Run tests.

### Task 38: AgentSchedulerPage.vue — List pagination

**Files:** `NeurUI/src/pages/AgentSchedulerPage.vue`

- [ ] **Step 1:** Add `a-pagination` below scheduler task list.

- [ ] **Step 2:** Run tests.

### Task 39: ToolLayerPage.vue — Grid pagination

**Files:** `NeurUI/src/pages/ToolLayerPage.vue`

- [ ] **Step 1:** Add `a-pagination` below server grid.

- [ ] **Step 2:** Run tests.

---

## Phase 4: Empty States (7 issues)

Add `a-empty` to tables/lists that show nothing when data is empty.

### Task 40: MemoryPage.vue — Empty state

**Files:** `NeurUI/src/pages/MemoryPage.vue`

- [ ] **Step 1:** Add `:locale="{ emptyText: '' }"` to table and render `a-empty` when `memories.length === 0`.

- [ ] **Step 2:** Run tests.

### Task 41: KnowledgePage.vue — Empty state

**Files:** `NeurUI/src/pages/KnowledgePage.vue`

- [ ] **Step 1:** Add empty state to table.

- [ ] **Step 2:** Run tests.

### Task 42: AuditPage.vue — Empty state

**Files:** `NeurUI/src/pages/AuditPage.vue`

- [ ] **Step 1:** Add empty state to table.

- [ ] **Step 2:** Run tests.

### Task 43: FilePage.vue — Empty state

**Files:** `NeurUI/src/pages/FilePage.vue`

- [ ] **Step 1:** Add empty state to table.

- [ ] **Step 2:** Run tests.

### Task 44: LogPage.vue — Empty state

**Files:** `NeurUI/src/pages/LogPage.vue`

- [ ] **Step 1:** Add empty state to table.

- [ ] **Step 2:** Run tests.

### Task 45: FirewallPage.vue — Empty state

**Files:** `NeurUI/src/pages/FirewallPage.vue`

- [ ] **Step 1:** Add empty state to both rules table and blocked logs table.

- [ ] **Step 2:** Run tests.

### Task 46: AgentFilePage.vue — Empty state

**Files:** `NeurUI/src/pages/AgentFilePage.vue`

- [ ] **Step 1:** Add empty state to table.

- [ ] **Step 2:** Run tests.

---

## Phase 5: Loading States (3 issues)

### Task 47: ChannelIntegrationPage.vue — Loading state

**Files:** `NeurUI/src/pages/ChannelIntegrationPage.vue`

- [ ] **Step 1:** Add `loadingConfigs` ref. Set true before `loadConfigs()`, false after. Wrap config list in `a-spin :spinning="loadingConfigs"`.

- [ ] **Step 2:** Run tests.

### Task 48: ModelPage.vue — Loading state for models

**Files:** `NeurUI/src/pages/ModelPage.vue`

- [ ] **Step 1:** Add `loadingModels` ref. Set true before `fetchModels()`, false after. Wrap model list in `a-spin`.

- [ ] **Step 2:** Run tests.

---

## Final Verification

### Task 49: Full build + test suite

- [ ] **Step 1:** Run `cd NeurUI && npx vitest run` — all 168+ tests must pass.

- [ ] **Step 2:** Run `cd NeurUI && npx vite build` — must build cleanly.

- [ ] **Step 3:** Spot-check 5 modified pages in browser to verify UI changes render correctly.
