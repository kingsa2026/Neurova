import React, { useEffect, useState } from 'react';
import { PageContainer } from '@ant-design/pro-components';
import { Card, Table, Tag, Space, Button, Modal, Form, Input, Select } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import type { Computer } from '@/types/computer';
import { computerApi } from '@/api/computer';

export function ComputerManagement() {
  const [computers, setComputers] = useState<Computer[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingComputer, setEditingComputer] = useState<Computer | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    loadComputers();
  }, []);

  const loadComputers = async () => {
    try {
      setLoading(true);
      // Use API to fetch computers (replace with actual implementation)
      const data = await computerApi.getComputers();
      setComputers(data || []);
    } catch (err) {
      console.error('Failed to load computers:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = () => {
    setEditingComputer(null);
    form.resetFields();
    setModalVisible(true);
  };

  const handleEdit = (computer: Computer) => {
    setEditingComputer(computer);
    form.setFieldsValue(computer);
    setModalVisible(true);
  };

  const handleDelete = (computerId: string) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除计算机 "${computerId}" 吗？`,
      okText: '删除',
      cancelText: '取消',
      onOk: async () => {
        try {
          await computerApi.deleteComputer(computerId);
          loadComputers();
        } catch (err) {
          console.error('Failed to delete computer:', err);
        }
      },
    });
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      
      if (editingComputer) {
        // Update existing
        await computerApi.updateComputer(editingComputer.computer_id, values);
      } else {
        // Create new
        await computerApi.createComputer(values);
      }
      
      setModalVisible(false);
      loadComputers();
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  const columns = [
    {
      title: 'ID',
      dataIndex: 'computer_id',
      key: 'computer_id',
      width: 200,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => <strong>{name}</strong>,
    },
    {
      title: '类型',
      dataIndex: 'kind',
      key: 'kind',
      render: (kind: string) => (
        <Tag color={getKindColor(kind)}>{kind}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>
          {status === 'online' ? '在线' : status}
        </Tag>
      ),
    },
    {
      title: 'CPU',
      dataIndex: 'cpu_info',
      key: 'cpu_info',
      ellipsis: true,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Computer) => (
        <Space>
          <Button 
            icon={<EditOutlined />} 
            size="small" 
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Button 
            danger 
            icon={<DeleteOutlined />} 
            size="small"
            onClick={() => handleDelete(record.computer_id)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  const getKindColor = (kind: string): string => {
    const colors: Record<string, string> = {
      local: 'blue',
      cloud: 'green',
      remote: 'purple',
    };
    return colors[kind] || 'default';
  };

  const getStatusColor = (status: string): string => {
    return status === 'online' ? 'success' : 'default';
  };

  return (
    <PageContainer header={{ title: '计算机管理' }}>
      {/* Action Bar */}
      <div style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
          添加计算机
        </Button>
      </div>

      {/* Computers Table */}
      <Card>
        <Table
          loading={loading}
          dataSource={computers}
          columns={columns}
          rowKey="computer_id"
          pagination={{ pageSize: 10 }}
          size="middle"
        />
      </Card>

      {/* Add/Edit Modal */}
      <Modal
        title={editingComputer ? '编辑计算机' : '添加计算机'}
        visible={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={handleSubmit}
        okText={editingComputer ? '保存' : '创建'}
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="例如：Cloud Server 1" />
          </Form.Item>

          <Form.Item
            name="kind"
            label="类型"
            rules={[{ required: true, message: '请选择类型' }]}
          >
            <Select>
              <Select.Option value="local">Local</Select.Option>
              <Select.Option value="cloud">Cloud</Select.Option>
              <Select.Option value="remote">Remote</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="description"
            label="描述"
          >
            <Input.TextArea rows={3} placeholder="可选描述" />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
