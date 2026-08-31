# Bug Fix: DELETE /models/{model_id} Returns 404

**Date:** 2026-06-18
**Severity:** Medium (model deletion broken)
**Status:** Fixed

## Summary

Clicking the delete button on a model in the model management modal returns `DELETE /api/v1/models/{model_id} 404 (Not Found)`. The backend `model.py` endpoint file had no `DELETE` route registered.

## Root Cause

**File:** `neurova/api/endpoints/model.py`

The model endpoint file only registered these routes:
- `GET /` — list models
- `GET /active` — get active model
- `POST /switch` — switch model
- `POST /probe-multimodal` — probe multimodal
- `POST /check-connection` — check connection

**Missing:** `DELETE /{model_id}` — no route to delete a model.

Meanwhile, the frontend `models.ts:35` calls `api.delete(\`${BASE}/${modelId}\`)`, which sends `DELETE /api/v1/models/sensenova-6.7-flash-lite` → 404.

## Fix

Added `DELETE /{model_id}` endpoint to `neurova/api/endpoints/model.py`:

1. Iterates all providers via `provider_manager.list_providers()`
2. Finds the provider whose `models` list contains the target `model_id`
3. Removes the model from the list
4. Calls `provider_manager.update_provider()` to persist the change
5. Returns 404 if no provider owns the model

## Files Changed

- `neurova/api/endpoints/model.py` — Added `Path` import + `delete_model` endpoint
- `tests/unit/llm/test_provider_manager.py` — Added `TestDeleteModel` class (5 tests)
