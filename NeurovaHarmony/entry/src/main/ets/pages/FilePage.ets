/**
 * FilePage - 文件管理页
 *
 * 职责：展示文件列表，按 parentId 形成树形结构，按 type 筛选 file/folder，
 *   支持面包屑导航、上传、删除
 * 设计：
 *   - FileViewHelper（导出）：纯视图模型，封装文件类型图标/颜色映射、
 *     文件大小格式化（B/KB/MB/GB）、修改时间格式化、面包屑路径构建、
 *     文件名截断，无 UI 运行时依赖，可独立单元测试；
 *   - FilePage（@Component）：Stack[Column[TopNavMenu(标题"文件"+返回+上传)]
 *     + [面包屑导航]
 *     + [type 筛选 Tab（全部/folder/file）]
 *     + [加载态/空态/列表] + [新建文件夹弹窗]]；
 *     列表项 GlassCard 含 文件类型图标、名称、大小、修改时间、操作按钮（删除）；
 *     点击文件夹 → 进入子目录（更新 parentId）；
 *     删除走 AlertDialog 二次确认；上传走 api.monitor.uploadFile；
 *     弹窗内嵌 Stack 条件渲染；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.monitor，消息走 MessageManager
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（monitor.listFiles/getFile/uploadFile/removeFile/createFolder）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：FileItem、FileItemType
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.monitor.listFiles(undefined) 加载根目录；
 *   type 筛选 Tab 切换 → 本地 filterByType 过滤；
 *   点击文件夹 → 更新 currentParentId → 重新加载该目录；
 *   面包屑点击 → 跳回对应层级；
 *   上传按钮 → 打开新建文件夹弹窗 → 调用 api.monitor.uploadFile → 刷新列表；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.monitor.removeFile → 刷新列表
 *
 * TDD：FileViewHelper 各方法按红绿灯垂直切片逐步实现，详见 FilePage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { FileItem, FileItemType } from '../libs/types';

/** 日志标签 */
const TAG = 'FilePage';

/** 默认文件名截断长度（文件页为 100 字符） */
const DEFAULT_TRUNCATE_LEN = 100;

/** 文件大小单位 */
const SIZE_UNITS = ['B', 'KB', 'MB', 'GB'];

/** 文件大小进制 */
const SIZE_BASE = 1024;

// ===========================================================================
// FileViewHelper - 文件视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'primary'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class FileViewHelper {
  /**
   * 获取文件项类型对应的图标 emoji
   * 映射：folder→📁，file 按 mimeType 前缀→🖼️(image)/🎵(audio)/🎬(video)/📄(其他)
   * @param type 文件项类型
   * @param mimeType 可选 MIME 类型
   * @return emoji 字符串
   */
  static getFileTypeIcon(type: FileItemType, mimeType?: string): string {
    if (type === 'folder') return '📁';
    if (!mimeType) return '📄';
    if (mimeType.startsWith('image/')) return '🖼️';
    if (mimeType.startsWith('audio/')) return '🎵';
    if (mimeType.startsWith('video/')) return '🎬';
    return '📄';
  }

  /**
   * 获取文件项类型对应的颜色 token 名
   * 映射：folder→primary（强调色，引导进入子目录），file→text_secondary（普通色）
   * @param type 文件项类型
   * @return StyleManager 颜色 token 名
   */
  static getFileTypeColor(type: FileItemType): string {
    if (type === 'folder') return 'primary';
    return 'text_secondary';
  }

  /**
   * 格式化文件大小为带单位的字符串
   * 规则：
   *   - 0 或负数 → "0 B"
   *   - 自动选择 B/KB/MB/GB 单位，保留 1 位小数
   *   - 参考 NeurUI FilePage.vue 的 formatFileSize 函数
   * @param bytes 字节数
   * @return 格式化后的大小字符串
   */
  static formatFileSize(bytes: number): string {
    if (!bytes || bytes <= 0) return '0 B';
    const i = Math.floor(Math.log(bytes) / Math.log(SIZE_BASE));
    // 防止超出单位数组范围（超过 GB 仍按 GB 显示）
    const unitIndex = Math.min(i, SIZE_UNITS.length - 1);
    const value = bytes / Math.pow(SIZE_BASE, unitIndex);
    return `${value.toFixed(1)} ${SIZE_UNITS[unitIndex]}`;
  }

  /**
   * 格式化 ISO 修改时间为 YYYY-MM-DD HH:mm
   * 规则：无值或无效 → "-"
   * @param timestamp ISO 时间戳字符串
   * @return 格式化时间或 "-"
   */
  static formatModifiedAt(timestamp?: string): string {
    if (!timestamp || timestamp.length === 0) return '-';
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '-';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const HH = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${HH}:${mm}`;
  }

  /**
   * 构建从根目录到当前 parentId 的面包屑路径数组
   * 规则：
   *   - parentId 为 undefined/空 → 返回 ['根目录']
   *   - parentId 在 files 中找不到 → 返回 ['根目录']
   *   - 正常情况 → 从根到当前的文件夹名称数组
   *   - 含循环检测，防止 parentId 链成环导致死循环
   * @param parentId 当前目录的父 id
   * @param files 全量文件列表（用于回溯查找）
   * @return 面包屑路径数组
   */
  static buildPath(parentId: string | undefined, files: FileItem[]): string[] {
    if (!parentId || parentId.length === 0) return ['根目录'];
    const path: string[] = [];
    const visited = new Set<string>();
    let current: string | undefined = parentId;
    while (current) {
      // 循环检测：若已访问过则跳出，防止死循环
      if (visited.has(current)) break;
      visited.add(current);
      const item = files.find((f: FileItem) => f.id === current);
      if (!item) break;
      path.push(item.name);
      current = item.parentId;
    }
    if (path.length === 0) return ['根目录'];
    path.reverse();
    return path;
  }

  /**
   * 截断文件名
   * 规则：
   *   - name 为空 → 原样返回
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param name 文件名
   * @param maxLen 最大长度，默认 100
   * @return 截断后的文件名
   */
  static truncateFileName(name: string, maxLen?: number): string {
    const len = maxLen !== undefined ? maxLen : DEFAULT_TRUNCATE_LEN;
    if (!name || name.length === 0) return name;
    if (name.length <= len) return name;
    return name.substring(0, len) + '...';
  }
}

/** 筛选 Tab 配置 */
interface TypeFilterOption {
  value: string;
  label: string;
}

/** 类型筛选 Tab 列表（全部/folder/file） */
const TYPE_FILTERS: TypeFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'folder', label: '文件夹' },
  { value: 'file', label: '文件' },
];

/** 新建文件夹表单数据 */
interface FolderFormData {
  name: string;
}

@Component
export struct FilePage {
  // 文件列表
  @State files: FileItem[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的类型筛选值
  @State activeType: string = 'all';
  // 当前所在目录的 parentId（undefined 表示根目录）
  @State currentParentId: string = '';
  // 新建文件夹弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建文件夹表单数据（@State 嵌套属性变更整体重新赋值）
  @State formData: FolderFormData = { name: '' };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadFiles();
  }

  /**
   * 加载当前目录文件列表
   * 流程：调用 api.monitor.listFiles(parentId) → 写入 files
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadFiles(): Promise<void> {
    this.loading = true;
    try {
      const parentId = this.currentParentId.length > 0 ? this.currentParentId : undefined;
      const res = await this.api.monitor.listFiles(parentId, { page: 1, size: 200 });
      if (res.code === 0 && res.data) {
        this.files = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载文件失败', e as Error);
      this.msg.error('加载文件列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换类型筛选 Tab */
  private switchType(value: string): void {
    this.activeType = value;
  }

  /** 获取经类型筛选后的列表 */
  private getFilteredList(): FileItem[] {
    if (this.activeType === 'all') {
      return this.files;
    }
    return this.files.filter((f: FileItem) => f.type === this.activeType);
  }

  /** 获取当前面包屑路径 */
  private getBreadcrumb(): string[] {
    const parentId = this.currentParentId.length > 0 ? this.currentParentId : undefined;
    return FileViewHelper.buildPath(parentId, this.files);
  }

  /** 点击文件夹进入子目录 */
  private enterFolder(folderId: string): void {
    this.currentParentId = folderId;
    this.loadFiles();
  }

  /** 点击面包屑某一级，回到对应层级 */
  private clickBreadcrumb(index: number): void {
    const path = this.getBreadcrumb();
    if (index === 0) {
      // 点击"根目录"
      this.currentParentId = '';
    } else {
      // 找到该层级对应的 folder id
      const targetName = path[index];
      const folder = this.files.find((f: FileItem) => f.name === targetName && f.type === 'folder');
      if (folder) {
        this.currentParentId = folder.id;
      }
    }
    this.loadFiles();
  }

  /** 打开新建文件夹弹窗，重置表单 */
  private openCreateDialog(): void {
    this.formData = { name: '' };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建文件夹
   * 流程：组装 data → 调用 api.monitor.createFolder → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并提示用户
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name) {
      this.msg.warning('请填写文件夹名称');
      return;
    }
    try {
      const data: Partial<FileItem> = {
        name: this.formData.name,
        type: 'folder' as FileItemType,
        path: '/',
        size: 0,
        parentId: this.currentParentId.length > 0 ? this.currentParentId : undefined,
      };
      const res = await this.api.monitor.createFolder(data);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.showCreateDialog = false;
        this.loadFiles();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建文件夹失败', e as Error);
      this.msg.error('创建文件夹失败');
    }
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(file: FileItem): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除"${file.name}"吗？此操作不可撤销。`,
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
   * 流程：调用 api.monitor.removeFile → 成功后刷新列表
   * 异常：记录日志并提示用户
   */
  private async deleteFile(fileId: string): Promise<void> {
    try {
      const res = await this.api.monitor.removeFile(fileId);
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
        // 顶部导航栏：标题"文件" + 返回按钮 + 新建文件夹按钮
        TopNavMenu({
          title: '文件',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '新建文件夹',
            type: 'primary',
            size: 'small',
            onClick: () => { this.openCreateDialog(); }
          })
        }

        // 面包屑导航
        Scroll() {
          Row({ space: 4 }) {
            ForEach(this.getBreadcrumb(), (name: string, index: number) => {
              Text(name)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(index === this.getBreadcrumb().length - 1
                  ? this.sm.getColor('text_primary')
                  : this.sm.getColor('info'))
                .onClick(() => { this.clickBreadcrumb(index); })
              if (index < this.getBreadcrumb().length - 1) {
                Text('/')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_disabled'))
              }
            }, (name: string, index: number) => `${name}-${index}`)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 类型筛选 Tab
        Scroll() {
          Row({ space: 8 }) {
            ForEach(TYPE_FILTERS, (opt: TypeFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeType === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeType === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchType(opt.value); })
            }, (opt: TypeFilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 主体：加载态 / 空态 / 列表
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
        } else if (this.getFilteredList().length === 0) {
          Column() {
            Text('暂无文件')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredList(), (file: FileItem) => {
              ListItem() {
                this.buildFileCard(file)
              }
            }, (file: FileItem) => file.id)
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

      // 新建文件夹弹窗：内嵌 Stack 条件渲染
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 文件卡片构建器
  // ===========================================================================

  /** 单个文件卡片：类型图标 + 名称 + 大小 + 修改时间 + 删除按钮 */
  @Builder
  buildFileCard(file: FileItem) {
    GlassCard() {
      Column() {
        // 上部：类型图标 + 名称
        Row() {
          Text(FileViewHelper.getFileTypeIcon(file.type, file.mimeType))
            .fontSize(20)
          Text(FileViewHelper.truncateFileName(file.name, DEFAULT_TRUNCATE_LEN))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor(FileViewHelper.getFileTypeColor(file.type)))
            .margin({ left: 8 })
            .layoutWeight(1)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 底部行：大小 · 修改时间
        Row() {
          Text(FileViewHelper.formatFileSize(file.size))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(`修改：${FileViewHelper.formatModifiedAt(file.modifiedAt)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: 8 })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：删除（右对齐）；文件夹点击进入
        Row() {
          if (file.type === 'folder') {
            GlassButton({
              text: '进入',
              type: 'default',
              size: 'small',
              onClick: () => { this.enterFolder(file.id); }
            })
          }
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
  // 新建文件夹弹窗构建器
  // ===========================================================================

  /** 新建文件夹弹窗：name */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showCreateDialog = false; })

      // 面板层
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          Text('新建文件夹')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 名称
          Text('名称')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入文件夹名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, name: v }; }
          })
            .margin({ top: 4 })

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              size: 'medium',
              onClick: () => { this.showCreateDialog = false; }
            })
            GlassButton({
              text: '创建',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.submitCreate(); }
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
      .width('90%')
    }
    .width('100%')
    .height('100%')
  }
}
