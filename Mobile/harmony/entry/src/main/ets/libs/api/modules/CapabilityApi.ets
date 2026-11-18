/**
 * CapabilityApi - 能力层 API 模块（端点经后端源码核对 2026-11-16）
 *
 * 后端事实源（挂载见 endpoints/__init__.py）：
 *   rules_api.py @ /v1/rules：GET ""（裸数组 RuleInfo，project_id 过滤）、
 *     POST ""、GET|PUT|DELETE /{rule_id}（无分页信封）
 *   files_api.py @ /v1/files：GET ""（裸数组 FileInfo，按当前用户）、
 *     GET|PUT|DELETE /{file_id}、POST /upload（multipart，移动端通道待接入）
 *   media.py @ /v1/media：GET /list（信封 {code,data:{media,total,offset,limit}}）、
 *     GET|DELETE /{media_id}（写入走 /save multipart，移动端通道待接入）
 * 旧 /capability/* 路径后端不存在，全部退役。
 */
import { HttpClient } from '../HttpClient';
import { asEnvelope, asEnvelopeList } from '../envelope';
import {
  ApiResponse,
  PageParams,
  PageResult,
  Rule,
  AgentFile,
  MediaAsset,
} from '../../types';

/** 规则（rules_api.py RuleInfo 投影） */
interface RuleInfoDto {
  id: string;
  name: string;
  description: string;
  rule_type: string;
  condition: string;
  action: string;
  priority: string;
  active: boolean;
  project_id: string | null;
  execution_count: number;
  last_executed: number | null;
  created_at: number;
  updated_at: number;
}

/** 文件（files_api.py FileInfo 投影） */
interface FileInfoDto {
  file_id: string;
  filename: string;
  file_type: string;
  mime_type: string;
  size: number;
  version: string;
  status: string;
  user_id: string;
  agent_id: string;
  path: string;
  created_at: number;
  updated_at: number;
}

/** 媒体条目（media.py _media_store 记录投影） */
interface MediaItemDto {
  media_id: string;
  filename: string;
  media_type: string;
  mime_type: string;
  size: number;
  agent_id: string;
  user_id: string;
  created_at: number;
}

/** 媒体列表载荷（media.py GET /list data 投影） */
interface MediaListPayload {
  media: MediaItemDto[];
  total: number;
  offset: number;
  limit: number;
}

/** 秒级时间戳 → ISO 字符串（空值/0 回退 ''） */
function tsToIso(ts: number | null | undefined): string {
  if (ts === null || ts === undefined || ts <= 0) return '';
  return new Date(ts * 1000).toISOString();
}

/** 裸数组 → PageResult 本地分页（page 默认 1、size 默认 20） */
function pageOf<T>(arr: T[], params?: PageParams): PageResult<T> {
  const page = params && params.page !== undefined ? params.page : 1;
  const size = params && params.size !== undefined ? params.size : 20;
  const start = (Math.max(page, 1) - 1) * size;
  const items = arr.slice(start, start + size);
  const result: PageResult<T> = { items: items, total: arr.length, page: page, size: size };
  return result;
}

export class CapabilityApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  // ==================== Rule 规则（/v1/rules） ====================

  /** RuleInfo → Rule（单源映射；type/priority/status 归一化到前端词汇） */
  private static toRule(dto: RuleInfoDto): Rule {
    let type: 'permission' | 'restriction' | 'behavior' | 'workflow' = 'behavior';
    if (dto.rule_type === 'permission' || dto.rule_type === 'restriction' || dto.rule_type === 'workflow') {
      type = dto.rule_type;
    }
    let priority = 2;
    if (dto.priority === 'high') priority = 1;
    if (dto.priority === 'low') priority = 3;
    const rule: Rule = {
      id: dto.id,
      agentId: dto.project_id !== null ? dto.project_id : '',
      name: dto.name,
      type: type,
      status: dto.active ? 'active' : 'inactive',
      priority: priority,
      condition: dto.condition,
      action: dto.action,
      description: dto.description,
      createdAt: tsToIso(dto.created_at),
      updatedAt: tsToIso(dto.updated_at),
    };
    return rule;
  }

  /** 后端 priority 词汇 → 前端数值 */
  private static priorityToBackend(priority: number | undefined): string {
    if (priority !== undefined && priority <= 1) return 'high';
    if (priority !== undefined && priority >= 3) return 'low';
    return 'medium';
  }

  /** 单条响应解包：data 缺失即抛错（不返回半空信封） */
  private static unwrapOne<T>(res: ApiResponse<T>, what: string): ApiResponse<T> {
    if (res.code !== 0 || !res.data) {
      throw new Error(res.message && res.message.length > 0 ? res.message : `${what}失败`);
    }
    return res;
  }

  /** 规则单条契约探针（rules_api.py RuleInfo 裸对象归一用） */
  private static readonly RULE_PROBES: string[] = ['id', 'name', 'rule_type'];

  /** 列出规则（project_id 后端过滤；后端裸数组，边界归一后本地分页） */
  async listRules(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<Rule>>> {
    const query: Record<string, Object> = {};
    if (agentId.length > 0) {
      query['project_id'] = agentId;
    }
    const res = asEnvelopeList<RuleInfoDto>(await this.client.get<RuleInfoDto[]>('/rules', query));
    const arr = res.data as Object as RuleInfoDto[];
    const rules: Rule[] = [];
    for (const dto of arr) {
      rules.push(CapabilityApi.toRule(dto));
    }
    const mapped: ApiResponse<PageResult<Rule>> = {
      code: res.code,
      message: res.message,
      data: pageOf(rules, params),
    };
    return mapped;
  }

  /** 获取单条规则 */
  async getRule(ruleId: string): Promise<ApiResponse<Rule>> {
    const res = asEnvelope<RuleInfoDto>(await this.client.get<RuleInfoDto>(`/rules/${ruleId}`), CapabilityApi.RULE_PROBES);
    const ok = CapabilityApi.unwrapOne(res, '规则获取');
    const mapped: ApiResponse<Rule> = {
      code: ok.code,
      message: ok.message,
      data: CapabilityApi.toRule(ok.data as Object as RuleInfoDto),
    };
    return mapped;
  }

  /** 创建规则（RuleCreate 契约：name 必填；project_id 承载 agent 维度） */
  async createRule(data: Partial<Rule>): Promise<ApiResponse<Rule>> {
    const body: Record<string, Object> = {
      'name': data.name !== undefined ? data.name : '未命名规则',
      'description': data.description !== undefined ? data.description : '',
      'rule_type': data.type !== undefined ? data.type : 'custom',
      'condition': data.condition !== undefined ? data.condition : '',
      'action': data.action !== undefined ? data.action : '',
      'priority': CapabilityApi.priorityToBackend(data.priority),
    };
    if (data.agentId !== undefined && data.agentId.length > 0) {
      body['project_id'] = data.agentId;
    }
    const res = asEnvelope<RuleInfoDto>(await this.client.post<RuleInfoDto>('/rules', body), CapabilityApi.RULE_PROBES);
    const ok = CapabilityApi.unwrapOne(res, '规则创建');
    const mapped: ApiResponse<Rule> = {
      code: ok.code,
      message: ok.message,
      data: CapabilityApi.toRule(ok.data as Object as RuleInfoDto),
    };
    return mapped;
  }

  /** 更新规则（RuleUpdate 为可选字段全量提交） */
  async updateRule(ruleId: string, data: Partial<Rule>): Promise<ApiResponse<Rule>> {
    const body: Record<string, Object> = {};
    if (data.name !== undefined) body['name'] = data.name;
    if (data.description !== undefined) body['description'] = data.description;
    if (data.type !== undefined) body['rule_type'] = data.type;
    if (data.condition !== undefined) body['condition'] = data.condition;
    if (data.action !== undefined) body['action'] = data.action;
    if (data.priority !== undefined) body['priority'] = CapabilityApi.priorityToBackend(data.priority);
    const res = asEnvelope<RuleInfoDto>(await this.client.put<RuleInfoDto>(`/rules/${ruleId}`, body), CapabilityApi.RULE_PROBES);
    const ok = CapabilityApi.unwrapOne(res, '规则更新');
    const mapped: ApiResponse<Rule> = {
      code: ok.code,
      message: ok.message,
      data: CapabilityApi.toRule(ok.data as Object as RuleInfoDto),
    };
    return mapped;
  }

  /** 删除规则 */
  async removeRule(ruleId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/rules/${ruleId}`);
  }

  // ==================== AgentFile 智能体文件（/v1/files） ====================

  /** FileInfo → AgentFile（单源映射） */
  private static toAgentFile(dto: FileInfoDto): AgentFile {
    const file: AgentFile = {
      id: dto.file_id,
      agentId: dto.agent_id,
      name: dto.filename,
      path: dto.path,
      size: dto.size,
      mimeType: dto.mime_type,
      uploadedAt: tsToIso(dto.created_at),
      uploadedBy: dto.user_id,
    };
    return file;
  }

  /** 列出文件（后端按当前用户过滤；裸数组边界归一后，agent 维度本地过滤+本地分页） */
  async listFiles(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<AgentFile>>> {
    const res = asEnvelopeList<FileInfoDto>(await this.client.get<FileInfoDto[]>('/files'));
    const arr = res.data as Object as FileInfoDto[];
    const files: AgentFile[] = [];
    for (const dto of arr) {
      if (agentId.length > 0 && dto.agent_id !== agentId) {
        continue;
      }
      files.push(CapabilityApi.toAgentFile(dto));
    }
    const mapped: ApiResponse<PageResult<AgentFile>> = {
      code: res.code,
      message: res.message,
      data: pageOf(files, params),
    };
    return mapped;
  }

  /** 获取单条文件元数据 */
  async getFile(fileId: string): Promise<ApiResponse<AgentFile>> {
    const res = asEnvelope<FileInfoDto>(await this.client.get<FileInfoDto>(`/files/${fileId}`), ['file_id', 'filename']);
    const ok = CapabilityApi.unwrapOne(res, '文件获取');
    const mapped: ApiResponse<AgentFile> = {
      code: ok.code,
      message: ok.message,
      data: CapabilityApi.toAgentFile(ok.data as Object as FileInfoDto),
    };
    return mapped;
  }

  /** 创建文件记录：后端 /files/upload 为 multipart 实体上传，移动端通道待接入（显式失败） */
  async createFile(data: Partial<AgentFile>): Promise<ApiResponse<AgentFile>> {
    throw new Error('移动端文件上传通道待接入（后端 /files/upload 需 multipart 实体）');
  }

  /** 更新文件元数据（FileUpdateRequest：filename/status） */
  async updateFile(fileId: string, data: Partial<AgentFile>): Promise<ApiResponse<AgentFile>> {
    const body: Record<string, Object> = {};
    if (data.name !== undefined) body['filename'] = data.name;
    const res = asEnvelope<FileInfoDto>(await this.client.put<FileInfoDto>(`/files/${fileId}`, body), ['file_id', 'filename']);
    const ok = CapabilityApi.unwrapOne(res, '文件更新');
    const mapped: ApiResponse<AgentFile> = {
      code: ok.code,
      message: ok.message,
      data: CapabilityApi.toAgentFile(ok.data as Object as FileInfoDto),
    };
    return mapped;
  }

  /** 删除文件 */
  async removeFile(fileId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/files/${fileId}`);
  }

  // ==================== MediaAsset 媒体资产（/v1/media） ====================

  /** 媒体条目 → MediaAsset（单源映射；下载地址走 /media/download/{id}，前端暂存相对路径） */
  private static toMediaAsset(dto: MediaItemDto): MediaAsset {
    let type: 'image' | 'audio' | 'video' | 'document' = 'document';
    if (dto.media_type === 'image' || dto.media_type === 'audio' || dto.media_type === 'video') {
      type = dto.media_type;
    }
    const asset: MediaAsset = {
      id: dto.media_id,
      agentId: dto.agent_id,
      type: type,
      name: dto.filename,
      url: `/media/download/${dto.media_id}`,
      size: dto.size,
      createdAt: tsToIso(dto.created_at),
    };
    return asset;
  }

  /** 列出媒体资产（media.py GET /list 信封 data.media；total 为过滤后总数） */
  async listMedia(
    agentId: string,
    params?: PageParams,
  ): Promise<ApiResponse<PageResult<MediaAsset>>> {
    const res = await this.client.get<MediaListPayload>('/media/list', {
      'agent_id': agentId.length > 0 ? agentId : 'default',
      'limit': 100,
    });
    const assets: MediaAsset[] = [];
    if (res.data) {
      for (const dto of res.data.media) {
        assets.push(CapabilityApi.toMediaAsset(dto));
      }
      const result: PageResult<MediaAsset> = {
        items: assets,
        total: res.data.total,
        page: params && params.page !== undefined ? params.page : 1,
        size: params && params.size !== undefined ? params.size : 20,
      };
      const mapped: ApiResponse<PageResult<MediaAsset>> = {
        code: res.code,
        message: res.message,
        data: result,
      };
      return mapped;
    }
    throw new Error(res.message && res.message.length > 0 ? res.message : '媒体列表获取失败');
  }

  /** 获取单条媒体资产 */
  async getMedia(mediaId: string): Promise<ApiResponse<MediaAsset>> {
    const res = asEnvelope<MediaItemDto>(await this.client.get<MediaItemDto>(`/media/${mediaId}`), ['media_id']);
    const ok = CapabilityApi.unwrapOne(res, '媒体获取');
    const mapped: ApiResponse<MediaAsset> = {
      code: ok.code,
      message: ok.message,
      data: CapabilityApi.toMediaAsset(ok.data as Object as MediaItemDto),
    };
    return mapped;
  }

  /** 创建媒体记录：后端 /media/save 为 multipart 实体上传，移动端通道待接入（显式失败） */
  async createMedia(data: Partial<MediaAsset>): Promise<ApiResponse<MediaAsset>> {
    throw new Error('移动端媒体上传通道待接入（后端 /media/save 需 multipart 实体）');
  }

  /** 更新媒体记录（后端无 PUT 端点，显式失败） */
  async updateMedia(mediaId: string, data: Partial<MediaAsset>): Promise<ApiResponse<MediaAsset>> {
    throw new Error('后端暂未提供媒体更新端点');
  }

  /** 删除媒体资产 */
  async removeMedia(mediaId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/media/${mediaId}`);
  }

  /** 存储用量（GET /files/storage/info，StorageInfo 投影；系统设置「清除缓存」读数） */
  async storageInfo(): Promise<ApiResponse<StorageInfoDto>> {
    const res = await this.client.get<StorageInfoDto>('/files/storage/info');
    return asEnvelope<StorageInfoDto>(res, ['user_id', 'total_files', 'total_size']) as ApiResponse<StorageInfoDto>;
  }
}

/** 存储用量（files_api.py StorageInfo 投影） */
export interface StorageInfoDto {
  user_id: string;
  total_files: number;
  total_size: number;
  by_type: Record<string, number>;
}
