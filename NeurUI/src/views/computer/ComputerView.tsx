import React, { useEffect, useState } from 'react';
import { Card, List, Tag, Button, Space, Statistic, Row, Col, Divider } from 'antd';
import { DesktopOutlined, CloudOutlined, MonitorOutlined } from '@ant-design/icons';
import type { Computer } from '@/types/computer';
import { computerApi } from '@/api/computer';
import { StatusIndicator } from '@/components/StatusIndicator';

export function ComputerView() {
  const [computers, setComputers] = useState<Computer[]>([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({
    total: 0,
    online: 0,
    byoa: 0,
    cloud: 0,
  });

  useEffect(() => {
    loadComputers();
  }, []);

  const loadComputers = async () => {
    try {
      const data = await computerApi.listUserComputers();
      setComputers(data);
      
      // Calculate stats
      setStats({
        total: data.length,
        online: data.filter(c => c.status === 'online').length,
        byoa: data.filter(c => c.kind === 'local' || c.kind === 'vps').length,
        cloud: data.filter(c => c.kind === 'cloud').length,
      });
    } catch (error) {
      console.error('Failed to load computers:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <PageContainer header={{ title: 'Computers' }}>
      {/* Stats */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic 
              title="Total" 
              value={stats.total}
              prefix={<DesktopOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic 
              title="Online" 
              value={stats.online}
              prefix={<span style={{ color: '#52c41a' }}>&#9711;</span>}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic 
              title="Cloud" 
              value={stats.cloud}
              prefix={<CloudOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic 
              title="BYOA" 
              value={stats.byoa}
              prefix={<MonitorOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* Computers List */}
      <List
        loading={loading}
        dataSource={computers}
        renderItem={(computer) => (
          <Card key={computer.computer_id} className="mb-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <StatusIndicator 
                  status={computer.status} 
                  size="medium"
                />
                <div>
                  <h3 className="font-semibold text-lg">{computer.name}</h3>
                  <div className="text-sm text-gray-500 flex gap-2 mt-1">
                    <span>{computer.kind.toUpperCase()}</span>
                    <span>•</span>
                    <span>{computer.engine.toUpperCase()}</span>
                    {computer.is_byoa && (
                      <>
                        <span>•</span>
                        <Tag color="blue">BYOA</Tag>
                      </>
                    )}
                  </div>
                </div>
              </div>
              
              <Space>
                <Tag>{computer.agents?.length || 0} Agents</Tag>
                <Button type="primary">Manage</Button>
              </Space>
            </div>
            
            {/* Additional Info */}
            {computer.last_seen_at && (
              <div className="mt-2 text-xs text-gray-400">
                Last seen: {new Date(computer.last_seen_at * 1000).toLocaleString()}
              </div>
            )}
          </Card>
        )}
      />
    </PageContainer>
  );
}
