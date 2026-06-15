import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SynonymEntry {
  word: string
  synonyms: string[]
  category: string
  created_at: number
  updated_at: number
}

export interface SynonymStats {
  total_words: number
  total_synonyms: number
  categories: string[]
  config: SynonymConfig
}

export interface SynonymConfig {
  enabled: boolean
  max_expansions: number
  boost_exact: boolean
}

export interface SynonymConfigUpdate {
  enabled?: boolean
  max_expansions?: number
  boost_exact?: boolean
}

export interface TestSearchResult {
  original_query: string
  expanded_terms: string[]
  synonyms_enabled: boolean
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/synonyms'

/** Get synonym library statistics. */
export function getSynonymStats() {
  return api.get<ApiResponse<SynonymStats>>(`${BASE}/stats`)
}

/** Get all synonyms. */
export function getAllSynonyms(params?: { category?: string; limit?: number }) {
  return api.get<ApiResponse<SynonymEntry[]>>(BASE, { params })
}

/** Get synonyms for a word. */
export function getSynonyms(word: string) {
  return api.get<ApiResponse<SynonymEntry>>(`${BASE}/${word}`)
}

/** Add synonyms (merge with existing). */
export function addSynonyms(data: { word: string; synonyms: string[]; category?: string }) {
  return api.post<ApiResponse<SynonymEntry>>(BASE, data)
}

/** Set synonyms (overwrite). */
export function setSynonyms(data: { word: string; synonyms: string[]; category?: string }) {
  return api.put<ApiResponse<SynonymEntry>>(BASE, data)
}

/** Remove a single synonym from a word. */
export function removeSynonym(word: string, synonym: string) {
  return api.delete<ApiResponse<{ message: string }>>(`${BASE}/${word}/synonyms/${synonym}`)
}

/** Delete a word entirely. */
export function deleteWord(word: string) {
  return api.delete<ApiResponse<{ message: string }>>(`${BASE}/${word}`)
}

/** Get LLM config for synonyms. */
export function getLLMConfig() {
  return api.get<ApiResponse<SynonymConfig>>(`${BASE}/config/llm`)
}

/** Set LLM config for synonyms. */
export function setLLMConfig(data: SynonymConfigUpdate) {
  return api.put<ApiResponse<SynonymConfig>>(`${BASE}/config/llm`, data)
}

/** Test semantic search with synonyms. */
export function testSemanticSearch(data: { query: string; use_synonyms?: boolean }) {
  return api.post<ApiResponse<TestSearchResult>>(`${BASE}/test-search`, data)
}
