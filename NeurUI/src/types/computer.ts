/**
 * Computer 类型定义
 */

export type ComputerKind = 'cloud' | 'local' | 'vps';

export type ComputerEngine = 
  | 'managed'
  | 'claude'
  | 'codex'
  | 'grok'
  | 'cursor'
  | 'opencode'
  | 'pi'
  | 'gemini'
  | 'qwen'
  | 'antigravity'
  | 'zcode';

export type ComputerStatus = 'online' | 'offline' | 'busy';

export interface Computer {
  computer_id: string;
  name: string;
  kind: ComputerKind;
  engine: ComputerEngine;
  status: ComputerStatus;
  last_seen_at?: number;
  owner_user_id: string;
  company_id: string;
  agents: Record<string, any>;
  daemon_token?: string;
  daemon_version?: string;
  paired_at?: number;
  revoked_at?: number;
  credential_hash?: string;
  metadata: Record<string, any>;
  created_at: number;
  updated_at: number;
  
  // Computed properties
  is_byoa?: boolean;
}
