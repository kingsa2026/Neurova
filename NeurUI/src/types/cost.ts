/**
 * Cost Tracking 类型定义
 */

export type LLMProvider = 
  | 'openai'
  | 'anthropic'
  | 'gemini'
  | 'ollama'
  | 'openrouter'
  | 'novita'
  | 'orcarouter'
  | 'byoa-claude'
  | 'byoa-codex';

export type LLMDirection = 'input' | 'output';

export interface LLMCall {
  call_id: string;
  agent_id: string;
  turn_id?: string;
  session_id?: string;
  provider: LLMProvider;
  model: string;
  direction: LLMDirection;
  input_tokens: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  cost_usd: number;
  called_at: string;
  metadata: Record<string, any>;
}

export interface CostSummary {
  agent_id: string;
  period: {
    start: Date;
    end: Date;
  };
  summary: Array<{
    provider: string;
    model: string;
    total_input: number;
    total_output: number;
    total_cost: number;
  }>;
  total_cost: number;
}

export interface CostDetailed extends CostSummary {
  calls: LLMCall[];
}

export interface CostCalculation {
  provider: string;
  model: string;
  tokens: {
    input: number;
    output: number;
    cache_read: number;
    cache_write: number;
  };
  cost_usd: number;
}
