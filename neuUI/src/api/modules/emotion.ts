import { request } from '@/api';

export interface EmotionData {
  agent_id: string;
  emotion: string;
  intensity: number;
  valence: number;
  arousal: number;
  mood_history: Array<{
    emotion: string;
    intensity: number;
    timestamp: string;
  }>;
  triggers: string[];
  context: Record<string, unknown>;
  timestamp: string;
}

export interface PersonalityData {
  agent_id: string;
  personality: string;
  traits: Record<string, number>;
  values: Record<string, string>;
  goals: string[];
  interests: string[];
  communication_style: string;
  personality_traits?: Record<string, number>;
  core_values?: Record<string, string>;
}

export interface PersonalityReport {
  agent_id: string;
  current_personality: {
    traits: Record<string, number>;
    values: Record<string, string>;
    goals: string[];
    interests: string[];
    communication_style: string;
  };
  development_metrics: {
    conversation_count: number;
    learning_events: number;
    adaptation_score: number;
  };
  growth_history: Array<Record<string, unknown>[]>;
  recent_changes: Array<Record<string, unknown>>;
}

export const emotionAPI = {
  getAgentEmotion: (agentId: string) =>
    request.get(`/agents/${agentId}/emotion`),

  setAgentMoodHistory: (agentId: string, limit: number = 30) =>
    request.get(`/agents/${agentId}/emotion/history?limit=${limit}`),

  getPersonality: (agentId: string) =>
    request.get(`/agents/${agentId}/personality`),

  updatePersonality: (agentId: string, data: Partial<{
    traits?: Record<string, number>;
    values?: Record<string, string>;
    goals?: string[];
    interests?: string[];
    communication_style?: string;
  }>) =>
    request.put(`/agents/${agentId}/personality`, data),

  getPersonalityReport: (agentId: string) =>
    request.get(`/agents/${agentId}/personality/report`),
};
