/**
 * HomeApi - 工作台汇总 API 模块（同源 PC DashboardPage）
 *
 * 后端事实源：neurova/api/endpoints/home.py（挂 /v1）：
 *   GET /v1/home/data    裸 dict：welcome_message / quick_stats / stats /
 *                        memory_categories ...（无 code/data 信封）
 *   GET /v1/home/trends  7 天活跃趋势（labels+data）
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** /home/data 消费子集 */
export interface HomeDataDto {
  welcome_message: string;
  quick_stats: Record<string, Object>;
  stats: Record<string, Object>;
}

export class HomeApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 汇总数据（裸 dict） */
  async data(): Promise<HomeDataDto> {
    const res = await this.client.get<HomeDataDto>('/home/data');
    return res as Object as HomeDataDto;
  }

  /** 7 天趋势（裸 dict：labels/data） */
  async trends(): Promise<ApiResponse<Object>> {
    return this.client.get<Object>('/home/trends');
  }
}
