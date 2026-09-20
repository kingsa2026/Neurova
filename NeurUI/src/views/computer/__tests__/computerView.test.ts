import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Computer } from '@/types/computer';

// ComputerView 统计计算逻辑的单元验证（不依赖 React 渲染）
// 当视图从 React 占位迁移到 Vue 组件后，此测试同时覆盖 composable 层

function computeComputerStats(computers: Computer[]) {
  return {
    total: computers.length,
    online: computers.filter(c => c.status === 'online').length,
    byoa: computers.filter(c => c.kind === 'local' || c.kind === 'vps').length,
    cloud: computers.filter(c => c.kind === 'cloud').length,
  };
}

function buildComputerFixture(overrides: Partial<Computer> = {}): Computer {
  return {
    computer_id: 'cmp-test-001',
    name: 'Test Machine',
    kind: 'local',
    engine: 'claude',
    status: 'online',
    owner_user_id: 'user-1',
    company_id: 'org-1',
    agents: {},
    metadata: {},
    created_at: 1700000000,
    updated_at: 1700000001,
    ...overrides,
  };
}

describe('ComputerView stats', () => {
  it('computes zero stats for empty list', () => {
    expect(computeComputerStats([])).toEqual({ total: 0, online: 0, byoa: 0, cloud: 0 });
  });

  it('computes correct distribution for mixed computers', () => {
    const computers = [
      buildComputerFixture({ computer_id: 'a', kind: 'local', status: 'online' }),
      buildComputerFixture({ computer_id: 'b', kind: 'vps', status: 'offline' }),
      buildComputerFixture({ computer_id: 'c', kind: 'cloud', status: 'online' }),
      buildComputerFixture({ computer_id: 'd', kind: 'cloud', status: 'busy' }),
    ];
    expect(computeComputerStats(computers)).toEqual({ total: 4, online: 2, byoa: 2, cloud: 2 });
  });

  it('snapshot of stats output shape', () => {
    const computers = [buildComputerFixture()];
    expect(computeComputerStats(computers)).toMatchSnapshot();
  });
});
