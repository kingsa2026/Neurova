import { describe, it, expect } from 'vitest';
import type { CostSummary } from '@/types/cost';

// CostDashboard 数据聚合逻辑验证
// 覆盖 totalTokens 计算和 provider 颜色映射

function calculateTotalTokens(summary: CostSummary['summary']): number {
  if (!summary) return 0;
  return summary.reduce((sum, item) => sum + (item.total_input || 0) + (item.total_output || 0), 0);
}

function getColorByProvider(provider: string): string {
  const colorMap: Record<string, string> = {
    openai: 'green',
    anthropic: 'orange',
    google: 'blue',
    deepseek: 'purple',
  };
  return colorMap[provider?.toLowerCase()] ?? 'default';
}

describe('CostDashboard data logic', () => {
  it('returns 0 for null summary', () => {
    expect(calculateTotalTokens(null as any)).toBe(0);
  });

  it('sums input and output tokens correctly', () => {
    const summary = [
      { provider: 'openai', model: 'gpt-4', total_input: 100, total_output: 50, total_cost: 0.01 },
      { provider: 'anthropic', model: 'claude-3', total_input: 200, total_output: 150, total_cost: 0.02 },
    ];
    expect(calculateTotalTokens(summary as any)).toBe(500);
  });

  it('maps known providers to colors', () => {
    expect(getColorByProvider('openai')).toBe('green');
    expect(getColorByProvider('unknown-provider')).toBe('default');
  });

  it('snapshot of token calculation result', () => {
    const summary = [
      { provider: 'openai', model: 'gpt-4', total_input: 1000, total_output: 500, total_cost: 0.05 },
    ];
    expect({ totalTokens: calculateTotalTokens(summary as any) }).toMatchSnapshot();
  });
});
