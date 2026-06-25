/**
 * HealthApi - 系统健康 API 模块
 *
 * 职责：查询系统整体健康、单个服务健康、指标数据
 * 设计：通过 HttpClient 委托请求；统一返回 Promise<ApiResponse<T>>
 *
 * 用法：
 *   const api = ApiFacade.getInstance().health;
 *   const sys = await api.check();
 *   const db = await api.getService('db');
 *   const metrics = await api.getMetrics();
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, SystemHealth, ServiceHealth } from '../../types';

export class HealthApi {
  constructor(private client: HttpClient) {}

  /** 检查系统整体健康 */
  async check(): Promise<ApiResponse<SystemHealth>> {
    return this.client.get<SystemHealth>('/v1/health');
  }

  /** 获取单个服务健康状态 */
  async getService(serviceName: string): Promise<ApiResponse<ServiceHealth>> {
    return this.client.get<ServiceHealth>(`/v1/health/services/${serviceName}`);
  }

  /** 获取系统指标（数值字典） */
  async getMetrics(): Promise<ApiResponse<Record<string, number>>> {
    return this.client.get<Record<string, number>>('/v1/health/metrics');
  }
}
