import React, { useEffect, useState } from 'react';
import { PageContainer } from '@ant-design/pro-components';
import { Card, Row, Col, Statistic, Table, Tag, Space, Typography, Alert } from 'antd';
import { DollarCircleOutlined, ThunderboltOutlined, ClockCircleOutlined } from '@ant-design/icons';
import type { CostSummary } from '@/types/cost';
import { costApi } from '@/api/computer';

const { Text } = Typography;

export function CostDashboard() {
  const [costData, setCostData] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadCostSummary();
  }, []);

  const loadCostSummary = async () => {
    try {
      setLoading(true);
      // Use current agent ID (replace with actual logic)
      const data = await costApi.getAgentCostSummary("current_agent", 24);
      setCostData(data);
      setError(null);
    } catch (err) {
      console.error('Failed to load cost summary:', err);
      setError('Failed to load cost data');
    } finally {
      setLoading(false);
    }
  };

  const calculateTotalTokens = () => {
    if (!costData?.summary) return 0;
    return costData.summary.reduce((sum: number, item: any) => {
      return sum + (item.total_input || 0) + (item.total_output || 0);
    }, 0);
  };

  const columns = [
    {
      title: '服务商',
      dataIndex: 'provider',
      key: 'provider',
      render: (provider: string) => (
        <Tag color={getColorByProvider(provider)}>{provider}</Tag>
      ),
    },
    {
      title: '模型',
      dataIndex: 'model',
      key: 'model',
    },
    {
      title: '输入 Token',
      dataIndex: 'total_input',
      key: 'total_input',
      sorter: (a: any, b: any) => a.total_input - b.total_input,
    },
    {
      title: '输出 Token',
      dataIndex: 'total_output',
      key: 'total_output',
      sorter: (a: any, b: any) => a.total_output - b.total_output,
    },
    {
      title: '总 Token',
      key: 'total_tokens',
      render: (_: any, record: any) => {
        return (record.total_input || 0) + (record.total_output || 0);
      },
      sorter: (a: any, b: any) => {
        const aTotal = a.total_input + a.total_output;
        const bTotal = b.total_input + b.total_output;
        return aTotal - bTotal;
      },
    },
    {
      title: '成本 (USD)',
      dataIndex: 'total_cost',
      key: 'total_cost',
      render: (cost: number) => `$${cost.toFixed(4)}`,
      sorter: (a: any, b: any) => a.total_cost - b.total_cost,
      align: 'right' as const,
    },
  ];

  const getColorByProvider = (provider: string): string => {
    const colors: Record<string, string> = {
      openai: 'blue',
      anthropic: 'orange',
      gemini: 'green',
      ollama: 'purple',
    };
    return colors[provider] || 'default';
  };

  return (
    <PageContainer header={{ title: '成本仪表盘' }}>
      {/* Action Bar */}
      <Space style={{ marginBottom: 16 }}>
        <Button onClick={loadCostSummary} loading={loading}>
          刷新数据
        </Button>
      </Space>

      {/* Error Alert */}
      {error && (
        <Alert message={error} type="error" showIcon style={{ marginBottom: 16 }} />
      )}

      {/* Statistics Cards */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="今日花费"
              value={costData?.total_cost || 0}
              prefix="$"
              precision={4}
              suffix="USD"
              valueStyle={{ color: '#cf1322' }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
              <DollarCircleOutlined /> Cost tracking active
            </div>
          </Card>
        </Col>
        
        <Col span={6}>
          <Card>
            <Statistic
              title="总 Token"
              value={calculateTotalTokens()}
              icon={<ThunderboltOutlined />}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
              Input + Output tokens
            </div>
          </Card>
        </Col>
        
        <Col span={6}>
          <Card>
            <Statistic
              title="平均每次对话"
              value={costData?.total_cost / (costData.summary?.length || 1)}
              prefix="$"
              precision={4}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
              Per query average
            </div>
          </Card>
        </Col>
        
        <Col span={6}>
          <Card>
            <Statistic
              title="调用次数"
              value={costData?.summary?.length || 0}
              icon={<ClockCircleOutlined />}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
              Last 24 hours
            </div>
          </Card>
        </Col>
      </Row>

      {/* Cost Details Table */}
      <Card 
        title="成本明细 (Last 24 Hours)" 
        extra={
          <Button type="link" onClick={() => window.location.reload()}>
            Refresh
          </Button>
        }
      >
        <Table
          loading={loading}
          dataSource={costData?.summary || []}
          columns={columns}
          rowKey="provider"
          pagination={{ pageSize: 10 }}
          size="middle"
        />
      </Card>

      {/* Insights Section */}
      <Card title="成本洞察" style={{ marginTop: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          {costData && costData.total_cost > 1 && (
            <Alert
              message="高成本警告"
              description={`过去 24 小时花费 $${costData.total_cost.toFixed(2)}，建议优化查询策略`}
              type="warning"
              showIcon
            />
          )}
          
          {costData && costData.summary && costData.summary.length > 0 && (
            <>
              <Text strong>最贵模型:</Text>
              <Text>
                {costData.summary.sort((a, b) => b.total_cost - a.total_cost)[0]?.model}
                ($
                {costData.summary
                  .sort((a, b) => b.total_cost - a.total_cost)[0]
                  ?.total_cost.toFixed(4)}
                )
              </Text>
            </>
          )}
          
          <Text strong>建议:</Text>
          <ul style={{ margin: 0 }}>
            <li>简单查询使用 gpt-4o-mini 可节省 90% 成本</li>
            <li>启用缓存减少重复查询</li>
            <li>设置预算告警防止超支</li>
          </ul>
        </Space>
      </Card>
    </PageContainer>
  );
}
