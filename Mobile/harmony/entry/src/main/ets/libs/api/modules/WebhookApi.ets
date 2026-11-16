/**
 * WebhookApi - Webhook 管理 API 模块（P1-34 新增，端点经后端源码核对 2026-11-16）
 *
 * 后端事实源（webhooks.py @ /v1/webhooks，全部裸形状，边界归一）：
 *   GET    /webhooks               → [WebhookInfo{webhook_id,name,url,events,enabled,user_id,created_at,updated_at}]
 *   POST   /webhooks               ← {name,url,events,secret?} → WebhookInfo
 *   GET    /webhooks/{id}          → WebhookInfo
 *   PUT    /webhooks/{id}          ← {name?,url?,events?,enabled?} → WebhookInfo
 *   DELETE /webhooks/{id}          → {message}
 *   POST   /webhooks/{id}/test     ← {event_type?,payload?} → 投递结果
 *   GET    /webhooks/{id}/deliveries → [DeliveryInfo]
 */
import { HttpClient } from '../HttpClient';
import { asEnvelope, asEnvelopeList } from '../envelope';
import { ApiResponse, Webhook, WebhookEvent, WebhookStatus } from '../../types';

/** WebhookInfo 投影（webhooks.py） */
export interface WebhookInfoDto {
  webhook_id: string;
  name: string;
  url: string;
  events: string[];
  enabled: boolean;
  user_id: string;
  created_at: number;
  updated_at: number;
}

/** 创建 body（webhooks.py WebhookCreate 契约，蛇形字段） */
export interface WebhookUpsertBody {
  name: string;
  url: string;
  events: string[];
  secret?: string;
}

/** 更新 body（webhooks.py WebhookUpdate 契约，全可选） */
export interface WebhookUpdateBody {
  name?: string;
  url?: string;
  events?: string[];
  secret?: string;
  enabled?: boolean;
}

/** WebhookInfo → Webhook（单源映射；后端无触发计数/最近触发时间，诚实缺省） */
function toWebhook(dto: WebhookInfoDto): Webhook {
  const events: WebhookEvent[] = [];
  for (const e of dto.events) {
    events.push(e as WebhookEvent);
  }
  const status: WebhookStatus = dto.enabled ? 'active' : 'paused';
  const webhook: Webhook = {
    id: dto.webhook_id,
    name: dto.name,
    url: dto.url,
    events: events,
    status: status,
    successCount: 0,
    failureCount: 0,
    createdAt: dto.created_at > 0 ? new Date(dto.created_at * 1000).toISOString() : '',
    updatedAt: dto.updated_at > 0 ? new Date(dto.updated_at * 1000).toISOString() : '',
  };
  return webhook;
}

export class WebhookApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /**
   * Webhook 列表（GET /webhooks，裸数组边界归一后映射）。
   * 后端无触发计数汇总字段——逐 webhook 聚合 /deliveries 得到真实
   * 成功/失败计数与最近触发时间（webhook 数量小，可接受）。
   */
  async list(): Promise<ApiResponse<Webhook[]>> {
    const res = asEnvelopeList<WebhookInfoDto>(await this.client.get<WebhookInfoDto[]>('/webhooks'));
    const arr = (res.data ?? []) as WebhookInfoDto[];
    const webhooks: Webhook[] = [];
    for (const dto of arr) {
      const webhook = toWebhook(dto);
      const deliveriesRes = asEnvelopeList<Object>(await this.client.get<Object[]>(`/webhooks/${dto.webhook_id}/deliveries`));
      const rows = (deliveriesRes.data ?? []) as Array<Record<string, Object>>;
      let success = 0;
      let failure = 0;
      let lastAt = 0;
      for (const row of rows) {
        const status = String(row['status'] ?? '');
        if (status === 'delivered') {
          success++;
        } else if (status === 'failed') {
          failure++;
        }
        const ts = Number(row['created_at'] ?? 0);
        if (ts > lastAt) {
          lastAt = ts;
        }
      }
      webhook.successCount = success;
      webhook.failureCount = failure;
      if (lastAt > 0) {
        webhook.lastTriggeredAt = new Date(lastAt * 1000).toISOString();
      }
      webhooks.push(webhook);
    }
    return { code: res.code, message: res.message, data: webhooks } as ApiResponse<Webhook[]>;
  }

  /** 创建 Webhook（POST /webhooks，WebhookInfo 裸对象边界归一） */
  async create(body: WebhookUpsertBody): Promise<ApiResponse<Webhook>> {
    const res = await this.client.post<WebhookInfoDto>('/webhooks', body);
    const ok = asEnvelope<WebhookInfoDto>(res, ['webhook_id', 'name']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : 'Webhook 创建失败');
    }
    return { code: ok.code, message: ok.message, data: toWebhook(ok.data as Object as WebhookInfoDto) } as ApiResponse<Webhook>;
  }

  /** Webhook 详情（GET /webhooks/{id}，裸对象边界归一） */
  async get(webhookId: string): Promise<ApiResponse<Webhook>> {
    const res = await this.client.get<WebhookInfoDto>(`/webhooks/${webhookId}`);
    const ok = asEnvelope<WebhookInfoDto>(res, ['webhook_id', 'name']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : 'Webhook 获取失败');
    }
    return { code: ok.code, message: ok.message, data: toWebhook(ok.data as Object as WebhookInfoDto) } as ApiResponse<Webhook>;
  }

  /** 更新 Webhook（PUT /webhooks/{id}，裸对象边界归一） */
  async update(webhookId: string, body: WebhookUpdateBody): Promise<ApiResponse<Webhook>> {
    const res = await this.client.put<WebhookInfoDto>(`/webhooks/${webhookId}`, body);
    const ok = asEnvelope<WebhookInfoDto>(res, ['webhook_id', 'name']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : 'Webhook 更新失败');
    }
    return { code: ok.code, message: ok.message, data: toWebhook(ok.data as Object as WebhookInfoDto) } as ApiResponse<Webhook>;
  }

  /** 删除 Webhook（DELETE /webhooks/{id}，{message} 裸 dict 边界归一） */
  async remove(webhookId: string): Promise<ApiResponse<Object>> {
    const res = await this.client.delete<Object>(`/webhooks/${webhookId}`);
    return asEnvelope<Object>(res, ['message']) as ApiResponse<Object>;
  }

  /** 测试触发（POST /webhooks/{id}/test，{event_type?,payload?}；返回投递记录，delivered→code 0） */
  async testTrigger(webhookId: string, eventType?: string): Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {
      'event_type': eventType !== undefined && eventType.length > 0 ? eventType : 'test',
    };
    const res = await this.client.post<Object>(`/webhooks/${webhookId}/test`, body);
    const ok = asEnvelope<Object>(res, ['delivery_id', 'status']);
    const payload = (ok.data ?? {}) as Record<string, Object>;
    const delivered = String(payload['status'] ?? '') === 'delivered';
    return {
      code: delivered ? 0 : 1,
      message: String(payload['status'] ?? ok.message ?? ''),
      data: payload,
    } as ApiResponse<Object>;
  }

  /** 投递记录（GET /webhooks/{id}/deliveries，裸数组边界归一） */
  async deliveries(webhookId: string): Promise<ApiResponse<Object[]>> {
    const res = await this.client.get<Object[]>(`/webhooks/${webhookId}/deliveries`);
    return asEnvelopeList<Object>(res as ApiResponse<Object[]>);
  }
}
