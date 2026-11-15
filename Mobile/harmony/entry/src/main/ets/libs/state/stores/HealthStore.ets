/**
 * HealthStore - 系统健康检查状态
 */
import { StateManager } from '../StateManager';

const KEY_HEALTH = 'health:data';
const KEY_LAST_CHECK = 'health:last_check';

/** 单服务健康条目（HealthData.services 的值类型；ArkTS 禁止对象字面量作类型，故具名声明） */
export interface ServiceStatusEntry {
  status: string;
  latency?: number;
}

export interface HealthData {
  status: 'healthy' | 'degraded' | 'down';
  services: Record<string, ServiceStatusEntry>;
}

export class HealthStore {
  private state: StateManager = StateManager.getInstance();

  get health(): HealthData | undefined {
    return this.state.get<HealthData>(KEY_HEALTH);
  }

  setHealth(data: HealthData): void {
    this.state.set(KEY_HEALTH, data);
    this.state.set(KEY_LAST_CHECK, Date.now());
  }

  get lastCheckAt(): number {
    return this.state.get<number>(KEY_LAST_CHECK, 0);
  }
}
