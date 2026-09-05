import { request } from '@/api'

export interface SynonymWord {
  word: string
  synonyms: string[]
}

export interface SynonymStats {
  word_count: number
  total_synonyms: number
  average_synonyms: number
  file_path: string
}

export interface SynonymConfig {
  enable_llm_fallback: boolean
  llm_provider: string
  llm_api_url: string
  llm_api_key: string
  llm_model_id: string
  llm_temperature: number
  llm_max_tokens: number
}

export interface AddSynonymRequest {
  word: string
  synonyms: string[]
}

export interface SetSynonymsRequest {
  word: string
  synonyms: string[]
}

export interface SemanticSearchResult {
  original_query: string
  expanded_query: string
  synonyms_used: string[]
  llm_enhanced: boolean
  memory_count: number
}

export const synonymAPI = {
  // 同义词词典管理
  getStats: () => request.get<SynonymStats>('/memory/synonyms/stats'),
  
  getAll: () => request.get<{words: SynonymWord[]}>('/memory/synonyms'),
  
  getSynonyms: (word: string) => request.get<{word: string, synonyms: string[]}>('/memory/synonyms/' + encodeURIComponent(word)),
  
  addSynonyms: (data: AddSynonymRequest) => 
    request.post<{success: boolean, word: string, synonyms: string[]}>('/memory/synonyms/add', data),
  
  setSynonyms: (data: SetSynonymsRequest) => 
    request.post<{success: boolean, word: string, synonyms: string[]}>('/memory/synonyms/set', data),
  
  removeSynonym: (word: string, synonym: string) => 
    request.delete<{success: boolean}>('/memory/synonyms/' + encodeURIComponent(word) + '/synonym/' + encodeURIComponent(synonym)),
  
  deleteWord: (word: string) => 
    request.delete<{success: boolean}>('/memory/synonyms/' + encodeURIComponent(word)),
  
  loadFromFile: () => request.post<{success: boolean, word_count: number}>('/memory/synonyms/load'),
  
  saveToFile: () => request.post<{success: boolean, file_path: string}>('/memory/synonyms/save'),
  
  // LLM配置
  getLLMConfig: () => request.get<SynonymConfig>('/memory/synonyms/llm-config'),
  
  setLLMConfig: (data: Partial<SynonymConfig>) => 
    request.post<{success: boolean}>('/memory/synonyms/llm-config', data),
  
  // 语义搜索测试
  testSemanticSearch: (query: string) => 
    request.post<SemanticSearchResult>('/memory/synonyms/test-search', { query }),
}
