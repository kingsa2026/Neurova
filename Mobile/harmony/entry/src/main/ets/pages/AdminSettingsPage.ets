/**
 * AdminSettingsPage - 系统设置（管理员，严格按设计稿 F17 还原）
 *
 * 常规：默认主题/默认语言（AppStore 真实值）、清除缓存（GET /files/storage/info 读数 +
 *       POST /settings/clear-cache 真清空 MemoryCache 注册表）。
 * 治理：GET /governance/agent-limits（仅管理员）真实键值行——执行档位（沙箱/评审/自动）
 *       后端无 /governance/settings 端点，档位裁决留在 PC 治理页（不设假档位开关）。
 * 关于：版本 App 1.0.0 · 服务端健康（GET /health 真实状态）。
 * 注意：行内数值直接读 State（@Builder 按值参数不随状态刷新，故不做通用行 Builder）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { AppStore } from '../libs/state/stores/AppStore';
import { IconBtn } from '../components/common/IconBtn';
import { AppIcon } from '../components/common/AppIcon';

/** 治理键 → 展示名（known keys 译名，未知键诚实保留原键） */
function limitLabelOf(key: string): string {
  if (key === 'token_budget') { return '会话 Token 预算'; }
  if (key === 'max_loop_rounds') { return '单轮工具轮次上限'; }
  if (key === 'goal_max_continuations') { return '目标续跑上限'; }
  if (key === 'goal_round_budget') { return '目标续跑轮次预算'; }
  if (key === 'goal_verification_enabled') { return '目标验收成本闸'; }
  if (key === 'max_subagent_depth') { return '子代理派生深度'; }
  if (key === 'max_parallel_tools') { return '工具并行上限'; }
  return key;
}

@Component
export struct AdminSettingsPage {
  @State private rows: string[][] = [];
  @State private loading: boolean = false;
  @State private cacheLabel: string = '';
  @State private serverHealth: string = '检查中…';
  @State private busy: boolean = false;
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();
  private appStore = new AppStore();

  aboutToAppear(): void {
    this.loadLimits();
    this.loadCache();
    this.loadHealth();
  }

  private async loadLimits(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.admin.agentLimits();
      if (res.code === 0 && res.data) {
        const obj = res.data as Record<string, Object>;
        const out: string[][] = [];
        const keys = Object.keys(obj);
        for (const k of keys) {
          const v = obj[k];
          out.push([limitLabelOf(k), typeof v === 'object' ? JSON.stringify(v) : `${v}`]);
        }
        this.rows = out;
      } else {
        this.msg.error(res.message || '治理设置获取失败');
      }
    } catch (e) {
      this.msg.error('治理设置获取失败：' + (e as Error).message);
    }
    this.loading = false;
  }

  private async loadCache(): Promise<void> {
    try {
      const res = await this.api.capability.storageInfo();
      if (res.code === 0 && res.data) {
        this.cacheLabel = this.formatSize(res.data.total_size) + ' · ' + res.data.total_files.toString() + ' 文件';
      } else {
        this.cacheLabel = '';
      }
    } catch (e) {
      this.cacheLabel = '';
    }
  }

  private async loadHealth(): Promise<void> {
    try {
      const res = await this.api.health.check();
      if (res.code === 0 && res.data) {
        this.serverHealth = '服务端' + (res.data.status === 'healthy' ? '健康' : res.data.status);
      } else {
        this.serverHealth = '服务端状态未知';
      }
    } catch (e) {
      this.serverHealth = '服务端不可达';
    }
  }

  private async clearCache(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const res = await this.api.settings.clearCache();
      if (res.code === 0) {
        this.msg.success('缓存已清空');
      } else {
        this.msg.error(res.message || '清缓存失败');
      }
    } catch (e) {
      this.msg.error('清缓存失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  private formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024) {
      return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }
    if (bytes >= 1024) {
      return (bytes / 1024).toFixed(0) + ' KB';
    }
    return bytes.toString() + ' B';
  }

  /** 分组标签（设计 .grp-lab） */
  @Builder
  groupLabel(icon: string, title: string) {
    Row() {
      AppIcon({ name: icon, iconSize: 11, color: this.sm.getColor('secondary') })
      Text(title)
        .fontSize(10.5)
        .fontColor(this.sm.getColor('text_tertiary'))
        .letterSpacing(0.8)
        .margin({ left: 5 })
    }
    .width('calc(100% - 40vp)')
    .margin({ left: 20, top: 14, bottom: 6 })
    .alignItems(VerticalAlign.Center)
  }

  build() {
    Column() {
      // 头部（设计 .phead：返回 + 系统设置）
      Row() {
        IconBtn({ name: 'back', onTap: () => { this.router.back(); } })
        Text('系统设置')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        Blank()
          .width(36)
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 6, bottom: 8 })

      Scroll() {
        Column() {
          this.groupLabel('gear', '常规')

          // 常规组（设计 .me-grp；数值直读 State 保证异步加载后刷新）
          Column() {
            Row() {
              Column() {
                AppIcon({ name: 'palette', iconSize: 14, color: this.sm.getColor('primary') })
              }
              .width(28)
              .height(28)
              .borderRadius(9)
              .backgroundColor(this.sm.getColor('primary_soft'))
              .justifyContent(FlexAlign.Center)
              .alignItems(HorizontalAlign.Center)
              Text('默认主题')
                .fontSize(13)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ left: 10 })
                .layoutWeight(1)
              Text(this.appStore.theme === 'dark' ? '星穹 · 深色' : '浅色')
                .fontSize(11.5)
                .fontColor(this.sm.getColor('text_tertiary'))
            }
            .width('100%')
            .padding({ top: 11, bottom: 11 })
            .alignItems(VerticalAlign.Center)

            Row() {
              Column() {
                AppIcon({ name: 'globe', iconSize: 14, color: this.sm.getColor('primary') })
              }
              .width(28)
              .height(28)
              .borderRadius(9)
              .backgroundColor(this.sm.getColor('primary_soft'))
              .justifyContent(FlexAlign.Center)
              .alignItems(HorizontalAlign.Center)
              Text('默认语言')
                .fontSize(13)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ left: 10 })
                .layoutWeight(1)
              Text(this.appStore.language === 'zh-CN' ? '简体中文' : this.appStore.language)
                .fontSize(11.5)
                .fontColor(this.sm.getColor('text_tertiary'))
            }
            .width('100%')
            .padding({ top: 11, bottom: 11 })
            .alignItems(VerticalAlign.Center)

            Row() {
              Column() {
                AppIcon({ name: 'folder', iconSize: 14, color: this.sm.getColor('primary') })
              }
              .width(28)
              .height(28)
              .borderRadius(9)
              .backgroundColor(this.sm.getColor('primary_soft'))
              .justifyContent(FlexAlign.Center)
              .alignItems(HorizontalAlign.Center)
              Text('清除缓存')
                .fontSize(13)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ left: 10 })
                .layoutWeight(1)
              Text(this.cacheLabel)
                .fontSize(11.5)
                .fontColor(this.sm.getColor('text_tertiary'))
              AppIcon({ name: 'chev', iconSize: 12, color: this.sm.getColor('text_tertiary') })
                .margin({ left: 4 })
            }
            .width('100%')
            .padding({ top: 11, bottom: 11 })
            .alignItems(VerticalAlign.Center)
            .opacity(this.busy ? 0.5 : 1)
            .onClick(() => { this.clearCache(); })
          }
          .width('calc(100% - 40vp)')
          .padding({ left: 15, right: 15 })
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ left: 20, right: 20, bottom: 6 })

          this.groupLabel('shield', '治理')

          // 治理组：agent-limits 真实键值（档位开关在 PC 治理页——后端无档位端点，不设假开关）
          Column() {
            if (this.rows.length === 0 && !this.loading) {
              Text(this.loading ? '加载中…' : '暂无治理键值')
                .fontSize(12.5)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 8, bottom: 8 })
            }
            ForEach(this.rows, (row: string[]) => {
              Row() {
                Text(row[0])
                  .fontSize(12.5)
                  .fontColor(this.sm.getColor('text_secondary'))
                  .layoutWeight(1)
                Text(row[1])
                  .fontSize(12.5)
                  .fontColor(this.sm.getColor('text_primary'))
                  .textAlign(TextAlign.End)
                  .constraintSize({ maxWidth: '55%' })
                  .maxLines(2)
              }
              .width('100%')
              .padding({ top: 9, bottom: 9 })
              .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
            }, (row: string[]) => row[0] + row[1])
            Text('执行档位与写回在 PC 治理页完成（后端未提供移动端档位端点）')
              .fontSize(9.5)
              .fontColor(this.sm.getColor('text_tertiary'))
              .margin({ top: 8 })
          }
          .width('calc(100% - 40vp)')
          .padding({ left: 15, right: 15, bottom: 10 })
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ left: 20, right: 20, bottom: 6 })

          this.groupLabel('info', '关于')

          // 关于组
          Column() {
            Row() {
              Column() {
                AppIcon({ name: 'spark', iconSize: 14, color: this.sm.getColor('primary') })
              }
              .width(28)
              .height(28)
              .borderRadius(9)
              .backgroundColor(this.sm.getColor('primary_soft'))
              .justifyContent(FlexAlign.Center)
              .alignItems(HorizontalAlign.Center)
              Text('版本')
                .fontSize(13)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ left: 10 })
                .layoutWeight(1)
              Text('App 1.0.0 · ' + this.serverHealth)
                .fontSize(11.5)
                .fontColor(this.sm.getColor('text_tertiary'))
            }
            .width('100%')
            .padding({ top: 11, bottom: 11 })
            .alignItems(VerticalAlign.Center)
          }
          .width('calc(100% - 40vp)')
          .padding({ left: 15, right: 15 })
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ left: 20, right: 20, bottom: 20 })
        }
        .width('100%')
      }
      .layoutWeight(1)
      .scrollBar(BarState.Off)
      .width('100%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
