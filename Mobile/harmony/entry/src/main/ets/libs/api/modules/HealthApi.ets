/**
 * HealthApi - 系统健康 API 模块（端点经后端源码核对 2026-11-16，P1-30）
 *
 * 后端事实源（health.py @ /v1/health，全部裸形状，边界归一）：
 *   GET /health          → HealthStatusResponse{status,timestamp,uptime,checks_count,...}
 *   GET /health/checks   → [CheckResultResponse{name,status,message,duration,check_type}]
 *   GET /health/checks/{name} → CheckResultResponse
 *   GET /health/report   → HealthReportResponse{status,checks,total_checks,...}
 * 旧 /health/services/*、/health/metrics 后端不存在：getService 改指 /health/checks/{name}，
 * getMetrics 诚实 throw 点名真实面。
 */
import { HttpClient } from '../HttpClient';
import { asEnvelope, asEnvelopeList } from '../envelope';
import { ApiResponse, SystemHealth, ServiceHealth } from '../../types';

/** HealthStatusResponse 投影（health.py） */
interface HealthStatusDto {
  status: string;
  timestamp: number;
  uptime: number;
  checks_count: number;
  healthy_count: number;
  unhealthy_count: number;
  message: string;
}

/** CheckResultResponse 投影（health.py） */
interface CheckResultDto {
  name: string;
  status: string;
  message: string;
  duration: number;
  check_type: string;
}

/** 后端检查状态 → 前端 ServiceHealth.status 词汇 */
function normCheckStatus(status: string): 'healthy' | 'degraded' | 'down' | 'unknown' {
  if (status === 'healthy') return 'healthy';
  if (status === 'degraded') return 'degraded';
  if (status === 'unhealthy' || status === 'down' || status === 'critical') return 'down';
  return 'unknown';
}

/** 后端整体状态 → 前端 SystemHealth.status 词汇 */
function normOverallStatus(status: string): 'healthy' | 'degraded' | 'down' {
  if (status === 'healthy') return 'healthy';
  if (status === 'degraded') return 'degraded';
  if (status === 'unhealthy' || status === 'critical' || status === 'down') return 'down';
  return 'degraded';
}

/** CheckResultResponse → ServiceHealth（单源映射；duration 为耗时毫秒） */
function toServiceHealth(dto: CheckResultDto): ServiceHealth {
  const service: ServiceHealth = {
    name: dto.name,
    status: normCheckStatus(dto.status),
    latency: dto.duration > 0 ? dto.duration : undefined,
    message: dto.message,
  };
  return service;
}

export class HealthApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /**
   * 检查系统整体健康：GET /health（总览）+ GET /health/checks（各项），
   * 边界归一并映射为 FE SystemHealth（score=健康项占比）。
   */
  async check(): Promise<ApiResponse<SystemHealth>> {
    const statusRes = asEnvelope<HealthStatusDto>(await this.client.get<HealthStatusDto>('/health'), ['status', 'timestamp']);
    if (statusRes.code !== 0 || !statusRes.data) {
      throw new Error(statusRes.message && statusRes.message.length > 0 ? statusRes.message : '健康状态获取失败');
    }
    const checksRes = asEnvelopeList<CheckResultDto>(await this.client.get<CheckResultDto[]>('/health/checks'));
    const checks = (checksRes.data ?? []) as CheckResultDto[];
    const services: ServiceHealth[] = [];
    for (const dto of checks) {
      services.push(toServiceHealth(dto));
    }
    const total = statusRes.data.checks_count > 0 ? statusRes.data.checks_count : checks.length;
    const healthy = statusRes.data.healthy_count;
    const health: SystemHealth = {
      status: normOverallStatus(statusRes.data.status),
      score: total > 0 ? Math.round((healthy / total) * 100) : 0,
      services: services,
      checkedAt: statusRes.data.timestamp > 0 ? new Date(statusRes.data.timestamp * 1000).toISOString() : new Date().toISOString(),
    };
    return { code: 0, message: statusRes.message, data: health } as ApiResponse<SystemHealth>;
  }

  /** 获取单个检查项健康状态（GET /health/checks/{name}，CheckResultResponse 边界归一） */
  async getService(serviceName: string): Promise<ApiResponse<ServiceHealth>> {
    const res = await this.client.get<CheckResultDto>(`/health/checks/${serviceName}`);
    const ok = asEnvelope<CheckResultDto>(res, ['name', 'status']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '服务健康获取失败');
    }
    return { code: ok.code, message: ok.message, data: toServiceHealth(ok.data as Object as CheckResultDto) } as ApiResponse<ServiceHealth>;
  }

  /** @deprecated 后端无 /health/metrics（系统资源真值走 GET /v1/stats/system 与 /v1/monitor/resources） */
  async getMetrics(): Promise<ApiResponse<Record<string, number>>> {
    throw new Error('后端无此端点：GET /v1/health/metrics（资源指标走 GET /v1/stats/system 或 /v1/monitor/resources）');
  }
}
