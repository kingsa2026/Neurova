# Bug Fix: LLM Provider Card Model List Not Displaying

**Date:** 2026-06-18
**Severity:** High (UI broken, models not visible)
**Status:** Fixed

## Summary

On the LLM page, provider cards cannot display the list of already-added models. When clicking the "Models" button on a provider card, the model management modal shows an empty list, even though models exist in the backend configuration.

## Root Cause

Two interconnected failures in the data flow:

### 1. Backend `list_models` endpoint returns no real models

**File:** `neurova/api/endpoints/model.py:80`

```python
if hasattr(provider_manager, "get_all_models"):
    all_models = provider_manager.get_all_models()
```

The `LLMProviderManager` class (in `neurova/llm/provider_manager.py`) does **not** have a `get_all_models()` method. The `hasattr` check returns `False`, so the endpoint falls through to the default fallback (lines 97-108) which returns only a single hardcoded "Auto" model with `provider="system"`.

### 2. Frontend `fetchModels()` overwrites `model_count` to 0

**File:** `NeurUI/src/pages/ModelPage.vue:567-570`

```typescript
providers.value = providers.value.map((p) => {
  const models = allModels.value.filter((m) => m.provider_id === p.id || m.provider_id === p.name)
  return { ...p, models, model_count: models.length }
})
```

Since `allModels` only contains the "Auto" model with `provider_id: "system"`, no provider matches → all providers get `models: []` and `model_count: 0`. This **overwrites** the correct `model_count` that was set by `fetchProviders()`.

### 3. Backend `ProviderInfo` response model doesn't include models

**File:** `neurova/api/endpoints/provider.py:32-42`

The `ProviderInfo` response model only has `models_count: int = 0`, not the actual models list. So even though `ProviderConfig.models` stores model IDs, they're never sent to the frontend via the providers endpoint.

## Data Flow (Before Fix)

```
Frontend onMounted:
  1. fetchProviders() → GET /providers
     Backend: Returns ProviderInfo[] with models_count (int), NO models array
     Frontend: mergeProviders() creates Provider objects with models: []
     
  2. fetchModels() → GET /models  
     Backend: provider_manager.get_all_models() DOES NOT EXIST
              → Falls through to return single "Auto" model with provider="system"
     Frontend: allModels = [Auto model]
              → filters by provider_id === provider.id
              → NO matches found (system != openai, anthropic, etc.)
              → ALL providers get models: [], model_count: 0
              → This OVERWRITES the correct model_count from step 1
     
  3. User clicks "Models" button on provider card
     → openModelManagement(p) sets modelTarget = p
     → filteredModels reads live?.models ?? modelTarget.models
     → Both are [] → Empty model list displayed
```

## Fix

### 1. Add `get_all_models()` to `LLMProviderManager`

**File:** `neurova/llm/provider_manager.py`

Added a new method that aggregates models from all providers:

```python
def get_all_models(self) -> List[PydanticModelInfo]:
    """获取所有服务商的模型列表（聚合）"""
    all_models: List[PydanticModelInfo] = []
    for provider in self.list_providers():
        for model_id in provider.models:
            all_models.append(
                PydanticModelInfo(
                    id=model_id,
                    name=model_id,
                    owned_by=provider.id,
                )
            )
    return all_models
```

### 2. Fix field mapping in `model.py` endpoint

**File:** `neurova/api/endpoints/model.py:80-92`

Updated the endpoint to correctly map `PydanticModelInfo` fields to `ModelInfo` fields:

- `model.id` → `ModelInfo.model_id` (was `model.model_id`)
- `model.owned_by` → `ModelInfo.provider` (was `model.provider`)
- Default `status` → `"available"` (was `"unknown"`)

## Data Flow (After Fix)

```
Frontend onMounted:
  1. fetchProviders() → GET /providers
     Backend: Returns ProviderInfo[] with models_count (int), NO models array
     Frontend: mergeProviders() creates Provider objects with models: []
     
  2. fetchModels() → GET /models  
     Backend: provider_manager.get_all_models() NOW EXISTS
              → Returns all models with correct provider field
              → e.g., ModelInfo(model_id="gpt-4o", provider="openai")
     Frontend: allModels = [gpt-4o, gpt-3.5-turbo, ...]
              → filters by provider_id === provider.id
              → MATCHES found (openai == openai, anthropic == anthropic, etc.)
              → ALL providers get correct models and model_count
     
  3. User clicks "Models" button on provider card
     → openModelManagement(p) sets modelTarget = p
     → filteredModels reads live?.models
     → Returns correct model list → Models displayed correctly
```

## Verification

To verify the fix:

1. Start the backend: `python start.py --backend`
2. Start the frontend: `cd NeurUI && npm run dev`
3. Navigate to the LLM page
4. Click "Models" on any provider card (e.g., OpenAI)
5. The model list should now display all models configured for that provider

## Files Changed

- `neurova/llm/provider_manager.py` — Added `get_all_models()` method
- `neurova/api/endpoints/model.py` — Fixed field mapping in `list_models` endpoint
