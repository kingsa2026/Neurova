/**
 * envelope - 后端响应信封归一（移动端单一事实源，审计复核命中点 9 / P1-28 / P1-29）
 *
 * 后端返回形状三种并存：
 *   1. `{code,data,message}` 信封（console/notifications/collaboration history 等）
 *      ——原样通过；
 *   2. 裸数组 / 裸对象（rules/files/scheduler/trace/sleep/firewall/channel-configs/
 *      sync/logs/webhooks/tasks/projects/teams 等 FastAPI response_model 直返）
 *      ——在边界包成 `{code:0,message:'ok',data}`；
 *   3. `{success,...}` 裸 dict（channel-configs 写操作、neuron）——按 success 展开。
 *
 * 归一只允许发生在 API 模块边界（本文件 + 各 Api 模块内）；
 * 页面层一律消费 `ApiResponse<T>`，不再自行解包（P1-28/29 根因修复点）。
 */
import { ApiResponse } from '../types';

/** 裸数组判定：HttpClient 透传的响应体本身就是数组 */
export function isBareArray(res: Object): boolean {
  return Array.isArray(res);
}

/** 裸对象判定：无信封字段（code/data），且携带目标契约的全部探针字段 */
export function isBareShape(res: Object, probeKeys: string[]): boolean {
  const keys: string[] = Object.keys(res);
  if (keys.indexOf('code') !== -1 || keys.indexOf('data') !== -1) {
    return false;
  }
  for (const k of probeKeys) {
    if (keys.indexOf(k) === -1) {
      return false;
    }
  }
  return true;
}

/** 裸对象 → {code,data} 信封（已是信封则原样返回） */
export function asEnvelope<T>(res: ApiResponse<T>, probeKeys: string[]): ApiResponse<T> {
  if (isBareShape(res as Object, probeKeys)) {
    const wrapped: ApiResponse<T> = { code: 0, message: 'ok', data: res as Object as T };
    return wrapped;
  }
  return res;
}

/** 裸数组 → {code,data} 信封（data=数组本体；已是信封则原样返回） */
export function asEnvelopeList<T>(res: ApiResponse<T[]>): ApiResponse<T[]> {
  if (Array.isArray(res as Object)) {
    const wrapped: ApiResponse<T[]> = { code: 0, message: 'ok', data: res as Object as T[] };
    return wrapped;
  }
  return res;
}

/** {success,data} 裸 dict（neuron 形）→ {code,data} 信封；success=false → code=1 */
export function asEnvelopeSuccessData<T>(res: ApiResponse<T>): ApiResponse<T> {
  const keys: string[] = Object.keys(res as Object);
  if (keys.indexOf('code') === -1 && keys.indexOf('success') !== -1 && keys.indexOf('data') !== -1) {
    const rec = res as Object as Record<string, Object>;
    const wrapped: ApiResponse<T> = {
      code: rec['success'] === true ? 0 : 1,
      message: '',
      data: rec['data'] as T,
    };
    return wrapped;
  }
  return res;
}
