/**
 * AgentFilePage - 智能体文件管理页
 *
 * 职责：展示当前 Agent 的文件列表，支持按 mimeType 筛选、上传、下载、删除
 * 设计：
 *   - AgentFileViewHelper（导出）：纯视图模型，封装 mimeType 图标映射、mimeType 标签映射、
 *     文件大小格式化、时间格式化；无 UI 运行时依赖，可独立单元测试；
 *   - AgentFilePage（@Component）：Column [TopNavMenu(标题"文件管理"+返回+上传)]
 *     + [mimeType 筛选 Tab（全部/图片/视频/音频/文档/其他）]
 *     + [加载态/空态/列表]；列表项 GlassCard 含文件名、mimeType 图标、大小（格式化）、
 *     上传时间、上传人、操作（下载/删除）；
 *     删除走 AlertDialog 二次确认；上传走内嵌 Stack 条件渲染的弹窗；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.capability，
 *     状态走 AgentsStore，消息走 MessageManager。
 *
 * 视图模型层（AgentFileViewHelper）：
 *   - 刻意设计为无 UI 依赖的纯函数集合，便于单元测试；
 *   - getMimeTypeIcon / getMimeTypeLabel 按 mimeType 前缀分类（image/*、video/*、audio/*、
 *     application/pdf、application/zip、text/*、其他）；
 *   - formatFileSize 按 1024 进制格式化为 B/KB/MB，0 → "—"；
 *   - formatTime 格式化为 YYYY-MM-DD HH:mm，无值回退 "未知"。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（capability 模块：listFiles/getFile/createFile/updateFile/removeFile）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：AgentFile
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.capability.listFiles(agentId) 加载列表；
 *   mimeType 筛选 Tab 切换 → 本地过滤；
 *   上传按钮 → 打开弹窗 → 填写 name/path/mimeType → api.capability.createFile → 刷新列表；
 *   下载按钮 → 提示"功能开发中"（M4 接入实际下载流）；
 *   删除按钮 → AlertDialog 二次确认 → api.capability.removeFile → 刷新列表。
 *
 * TDD：AgentFileViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AgentFilePage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { AgentFile } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentFilePage';

// ===========================================================================
// AgentFileViewHelper - 文件视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class AgentFileViewHelper {
  /**
   * 获取 mimeType 对应的图标 emoji
   * 映射：
   *   image/*          → 🖼️
   *   video/*          → 🎬
   *   audio/*          → 🎵
   *   application/pdf  → 📄
   *   text/*           → 📝
   *   application/zip  → 🗜️
   *   其他              → 📁
   * @param mimeType MIME 类型字符串
   * @return emoji 字符
   */
  static getMimeTypeIcon(mimeType: string): string {
    if (!mimeType) return '📁';
    if (mimeType.startsWith('image/')) return '🖼️';
    if (mimeType.startsWith('video/')) return '🎬';
    if (mimeType.startsWith('audio/')) return '🎵';
    if (mimeType === 'application/pdf') return '📄';
    if (mimeType.startsWith('text/')) return '📝';
    if (mimeType === 'application/zip') return '🗜️';
    return '📁';
  }

  /**
   * 获取 mimeType 对应的中文标签
   * 映射：
   *   image/*          → 图片
   *   video/*          → 视频
   *   audio/*          → 音频
   *   application/pdf  → PDF
   *   text/*           → 文本
   *   application/zip  → 压缩包
   *   其他              → 文件
   * @param mimeType MIME 类型字符串
   * @return 中文短名
   */
  static getMimeTypeLabel(mimeType: string): string {
    if (!mimeType) return '文件';
    if (mimeType.startsWith('image/')) return '图片';
    if (mimeType.startsWith('video/')) return '视频';
    if (mimeType.startsWith('audio/')) return '音频';
    if (mimeType === 'application/pdf') return 'PDF';
    if (mimeType.startsWith('text/')) return '文本';
    if (mimeType === 'application/zip') return '压缩包';
    return '文件';
  }

  /**
   * 将字节数格式化为人类可读字符串
   * 规则：1024 → "1.0 KB"，1048576 → "1.0 MB"，0 → "—"
   * 单位阶梯：B / KB / MB（按 1024 进制，保留 1 位小数）
   * @param bytes 字节数
   * @return 已格式化的字符串
   */
  static formatFileSize(bytes: number): string {
    if (bytes === 0) return '—';
    const KB = 1024;
    const MB = KB * 1024;
    if (bytes >= MB) {
      return (bytes / MB).toFixed(1) + ' MB';
    }
    if (bytes >= KB) {
      return (bytes / KB).toFixed(1) + ' KB';
    }
    return bytes + ' B';
  }

  /**
   * 格式化时间为 YYYY-MM-DD HH:mm
   * @param timeStr ISO 时间字符串
   * @return 格式化后的字符串；无效或空值返回 "未知"
   */
  static formatTime(timeStr?: string): string {
    if (!timeStr) return '未知';
    const d = new Date(timeStr);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }
}

// ===========================================================================
// 筛选 Tab 配置
// ===========================================================================

/** mimeType 筛选 Tab 选项 */
interface MimeTypeFilterOption {
  value: string;  // 'all' / 'image' / 'video' / 'audio' / 'document' / 'other'
  label: string;
}

/** mimeType 筛选 Tab 列表（顺序即展示顺序） */
const MIME_TYPE_FILTERS: MimeTypeFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'image', label: '图片' },
  { value: 'video', label: '视频' },
  { value: 'audio', label: '音频' },
  { value: 'document', label: '文档' },
  { value: 'other', label: '其他' },
];

/** 判断文件是否属于指定分类 */
function matchMimeTypeCategory(file: AgentFile, category: string): boolean {
  const mt = file.mimeType || '';
  switch (category) {
    case 'image':
      return mt.startsWith('image/');
    case 'video':
      return mt.startsWith('video/');
    case 'audio':
      return mt.startsWith('audio/');
    case 'document':
      return mt === 'application/pdf' || mt.startsWith('text/');
    case 'other':
      return !mt.startsWith('image/')
        && !mt.startsWith('video/')
        && !mt.startsWith('audio/')
        && mt !== 'application/pdf'
        && !mt.startsWith('text/');
    case 'all':
    default:
      return true;
  }
}

// ===========================================================================
// 表单数据
// ===========================================================================

/** 上传表单数据 */
interface FileFormData {
  name: string;
  path: string;
  mimeType: string;
}

/** 常用 mimeType 选项（用于表单选择） */
const MIME_TYPE_OPTIONS: string[] = [
  'image/png',
  'image/jpeg',
  'video/mp4',
  'audio/mpeg',
  'application/pdf',
  'text/plain',
  'application/zip',
  'application/octet-stream',
];

/** 表单默认值 */
function createEmptyForm(): FileFormData {
  return { name: '', path: '', mimeType: 'application/octet-stream' };
}

@Component
export struct AgentFilePage {
  // 文件列表（由 API 加载，驱动列表渲染）
  @State files: AgentFile[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 当前激活的 mimeType 筛选值
  @State activeMimeCategory: string = 'all';

  // 弹窗显示状态
  @State showDialog: boolean = false;
  // 上传表单数据（嵌套对象，变更必须整体重新赋值）
  @State formData: FileFormData = createEmptyForm();

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadFiles();
  }

  /**
   * 加载文件列表
   * 流程：取 currentAgentId → 调用 api.capability.listFiles → 写入 files
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadFiles(): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.loading = false;
      this.msg.warning('请先选择智能体');
      return;
    }
    this.loading = true;
    try {
      const res = await this.api.capability.listFiles(agentId);
      if (res.code === 0 && res.data) {
        this.files = res.data.items;
      } else {
        this.msg.error(res.message || '加载失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载文件失败', e as Error);
      this.msg.error('加载文件失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换 mimeType 筛选 Tab */
  private switchMimeCategory(value: string): void {
    this.activeMimeCategory = value;
  }

  /**
   * 获取经筛选后的列表
   */
  private getFilteredFiles(): AgentFile[] {
    if (this.activeMimeCategory === 'all') {
      return this.files;
    }
    return this.files.filter((f: AgentFile) => matchMimeTypeCategory(f, this.activeMimeCategory));
  }

  /**
   * 打开上传弹窗
   * 重置表单为默认值
   */
  private openUploadDialog(): void {
    this.formData = createEmptyForm();
    this.showDialog = true;
  }

  /** 关闭弹窗 */
  private closeDialog(): void {
    this.showDialog = false;
  }

  /**
   * 提交上传（创建文件记录）
   * 流程：表单校验 → api.capability.createFile → 刷新列表
   * 异常：记录日志并提示用户
   */
  private async submitUpload(): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.msg.warning('请先选择智能体');
      return;
    }
    if (!this.formData.name) {
      this.msg.warning('请填写文件名称');
      return;
    }
    if (!this.formData.path) {
      this.msg.warning('请填写文件路径');
      return;
    }
    try {
      const data: Partial<AgentFile> = {
        agentId,
        name: this.formData.name,
        path: this.formData.path,
        mimeType: this.formData.mimeType || 'application/octet-stream',
        size: 0,
      };
      const res = await this.api.capability.createFile(data);
      if (res.code === 0) {
        this.msg.success('上传成功');
        this.showDialog = false;
        this.loadFiles();
      } else {
        this.msg.error(res.message || '上传失败');
      }
    } catch (e) {
      this.logger.error(TAG, '上传文件失败', e as Error);
      this.msg.error('上传文件失败');
    }
  }

  /**
   * 下载文件（M4 接入实际下载流，当前提示"功能开发中"）
   */
  private downloadFile(file: AgentFile): void {
    this.msg.info(`下载 ${file.name}：功能开发中`);
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(file: AgentFile): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除文件"${file.name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteFile(file.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.capability.removeFile → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
  private async deleteFile(fileId: string): Promise<void> {
    try {
      const res = await this.api.capability.removeFile(fileId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadFiles();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除文件失败', e as Error);
      this.msg.error('删除文件失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"文件管理" + 返回 + 上传按钮
        TopNavMenu({
          title: '文件管理',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '上传',
            type: 'primary',
            size: 'small',
            onClick: () => { this.openUploadDialog(); }
          })
        }

        // mimeType 筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(MIME_TYPE_FILTERS, (opt: MimeTypeFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeMimeCategory === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeMimeCategory === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchMimeCategory(opt.value); })
            }, (opt: MimeTypeFilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 主体内容：加载态 / 空态 / 列表
        if (this.loading) {
          Column() {
            Text('加载中...')
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else if (this.getFilteredFiles().length === 0) {
          Column() {
            Text('暂无文件')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: this.sm.getSpacing('md') })
            GlassButton({
              text: '上传文件',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.openUploadDialog(); }
            })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredFiles(), (file: AgentFile) => {
              ListItem() {
                this.buildFileCard(file)
              }
            }, (file: AgentFile) => file.id)
          }
          .layoutWeight(1)
          .width('100%')
          .scrollBar(BarState.Off)
          .padding({
            left: this.sm.getSpacing('md'),
            right: this.sm.getSpacing('md'),
            top: this.sm.getSpacing('sm'),
            bottom: this.sm.getSpacing('sm'),
          })
        }
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.sm.getColor('background'))

      // 上传弹窗：内嵌 Stack 条件渲染
      if (this.showDialog) {
        this.buildUploadDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 文件卡片构建器
  // ===========================================================================

  /** 单条文件卡片：图标+名称 / mimeType 标签+大小 / 时间+上传人 / 操作按钮 */
  @Builder
  buildFileCard(file: AgentFile) {
    GlassCard() {
      Column() {
        // 上部：图标 + 文件名
        Row() {
          Text(AgentFileViewHelper.getMimeTypeIcon(file.mimeType))
            .fontSize(24)
            .width(40)
            .height(40)
            .textAlign(TextAlign.Center)
          Text(file.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // mimeType 标签 + 大小
        Row() {
          Text(AgentFileViewHelper.getMimeTypeLabel(file.mimeType))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor('info'))
          Text(AgentFileViewHelper.formatFileSize(file.size))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .margin({ top: 8 })
        .alignItems(VerticalAlign.Center)

        // 上传时间 + 上传人
        Row() {
          Text(`上传：${AgentFileViewHelper.formatTime(file.uploadedAt)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(`上传人：${file.uploadedBy ?? '未知'}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：下载 / 删除（右对齐）
        Row() {
          GlassButton({
            text: '下载',
            type: 'default',
            size: 'small',
            onClick: () => { this.downloadFile(file); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(file); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }

  // ===========================================================================
  // 上传弹窗构建器（内嵌 Stack 条件渲染）
  // ===========================================================================

  @Builder
  buildUploadDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDialog(); })

      // 面板层
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          Text('上传文件')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ bottom: this.sm.getSpacing('md') })
            .width('100%')

          // 文件名称
          Text('文件名称')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入文件名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, name: v }; }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 文件路径
          Text('文件路径')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入文件路径（如 /data/file.png）',
            value: this.formData.path,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, path: v }; }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // mimeType 选择
          Text('MIME 类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          Scroll() {
            Row({ space: 8 }) {
              ForEach(MIME_TYPE_OPTIONS, (mt: string) => {
                GlassButton({
                  text: mt,
                  type: this.formData.mimeType === mt ? 'primary' : 'default',
                  size: 'small',
                  onClick: () => {
                    this.formData = { ...this.formData, mimeType: mt };
                  }
                })
              }, (mt: string) => mt)
            }
            .padding({ top: 4, bottom: 4 })
          }
          .scrollable(ScrollDirection.Horizontal)
          .scrollBar(BarState.Off)
          .width('100%')
          .margin({ top: 4, bottom: this.sm.getSpacing('md') })

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              size: 'medium',
              onClick: () => { this.closeDialog(); }
            })
            GlassButton({
              text: '上传',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.submitUpload(); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .width('90%')
    }
    .width('100%')
    .height('100%')
  }
}
