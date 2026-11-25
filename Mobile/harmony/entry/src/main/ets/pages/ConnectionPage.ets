/**
 * ConnectionPage - 终端档案「连接」页（设计方案 §6.4 第 2 条，已裁 D4 多档案）
 *
 * 职责：列出/新增/切换/删除终端档案；切换后把地址落到 HTTP 装配点
 *       （ConfigManager.applyServerProfile），并要求以该终端账号重新登录。
 *
 * 设计：简化 ArkUI 列表页（List + TextInput），样式 token 走 StyleManager；
 *       终端地址不写死，全部来自本页档案。
 */

import { ServerProfiles, ServerProfile } from '../libs/config/ServerProfiles';
import { ConfigManager } from '../libs/config/ConfigManager';
import { Router, RouteNames } from '../routing/Router';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { StyleManager } from '../libs/style/StyleManager';
import { StarBackground } from '../components/glass';
import { AppIcon } from '../components/common/AppIcon';
import { IconBtn } from '../components/common/IconBtn';
import { GlassInput } from '../components/glass';
import { GlassButton } from '../components/glass';
import { AuthStore } from '../libs/state/stores/AuthStore';

const TAG = 'ConnectionPage';

@Entry
@Component
export struct ConnectionPage {
  @State profiles: ServerProfile[] = [];
  @State activeId: string = '';
  // 新增档案三要素：地址栏（IP/中继域名）+ 端口 + SSL（开=https，关=http）
  @State newHost: string = '';
  @State newPort: string = '';
  @State newSsl: boolean = false;
  @State newName: string = '';
  @State busy: boolean = false;

  private store = ServerProfiles.getInstance();
  private cm = ConfigManager.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();
  private authStore = new AuthStore();

  aboutToAppear() {
    this.refresh();
  }

  private refresh(): void {
    this.profiles = this.store.getList();
    const active = this.store.getActive();
    this.activeId = active ? active.id : '';
  }

  /** 切换档案：地址落 HTTP 装配点；要求以该终端账号重新登录 */
  private async useProfile(p: ServerProfile): Promise<void> {
    this.busy = true;
    try {
      // 先摘旧 bearer，再持久化激活状态；任何一步失败都不能把旧终端 token 带给新终端。
      await this.authStore.activateServer(p.id, p.baseUrl);
      if (!(await this.store.switchTo(p.id))) throw new Error('终端档案不存在');
      await this.cm.applyServerProfile(`${p.baseUrl}/api/v1`, getContext(this) as Context);
      this.refresh();
      this.msg.success(`已切换到 ${p.name}，请重新登录`);
      this.router.replace(RouteNames.LOGIN);
    } catch (e) {
      this.logger.error(TAG, '切换档案失败', e as Error);
      this.msg.error('切换失败');
    } finally {
      this.busy = false;
    }
  }

  private async addProfile(): Promise<void> {
    if (this.newHost.trim().length === 0) {
      this.msg.warning('请输入终端地址（IP 或中继域名）');
      return;
    }
    this.busy = true;
    try {
      const url = ServerProfiles.joinBaseUrl(this.newSsl, this.newHost, this.newPort);
      const added = await this.store.add(this.newName, url);
      this.newName = '';
      this.newHost = '';
      this.newPort = '';
      this.newSsl = false;
      // 新档案立即激活并进入扫码配对：二维码只带 ref 不带地址（§3.4），
      // 所以先录地址、再扫码配对，两步缺一不可
      await this.authStore.activateServer(added.id, added.baseUrl);
      if (!(await this.store.switchTo(added.id))) throw new Error('终端档案不存在');
      await this.cm.applyServerProfile(`${added.baseUrl}/api/v1`, getContext(this) as Context);
      this.refresh();
      this.activeId = added.id;
      this.msg.success('档案已添加，请扫码配对设备');
      this.router.replace(RouteNames.PAIRING);
    } finally {
      this.busy = false;
    }
  }

  private async removeProfile(id: string): Promise<void> {
    this.busy = true;
    try {
      const removedActive = this.store.getActive()?.id === id;
      await this.store.remove(id);
      this.authStore.forgetServer(id);
      if (removedActive) {
        const next = this.store.getActive();
        await this.authStore.activateServer(next ? next.id : '', next ? next.baseUrl : '');
        if (next) await this.cm.applyServerProfile(`${next.baseUrl}/api/v1`, getContext(this) as Context);
      }
      this.refresh();
    } finally {
      this.busy = false;
    }
  }

  build() {
    Stack() {
      StarBackground({ starCount: 60, twinkle: true })

      Column() {
        // 页头：返回 + 标题（21/700，设计 .phead）
        Row() {
          IconBtn({ name: 'back', onTap: () => { this.router.back(); } })
          Text('PC 终端')
            .fontSize(this.sm.getFontSize('page_title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ left: 12 })
        }
        .width('100%')
        .padding(16)
        .alignItems(VerticalAlign.Center)

        Scroll() {
          Column() {
            ForEach(this.profiles, (p: ServerProfile) => {
              Row() {
                Column() {
                  Text(p.name)
                    .fontSize(this.sm.getFontSize('card_title'))
                    .fontWeight(FontWeight.Medium)
                    .fontColor(this.sm.getColor('text_primary'))
                  Text(p.baseUrl)
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontFamily(this.sm.getMonoFont())
                    .fontColor(this.sm.getColor('text_secondary'))
                    .margin({ top: 2 })
                  Text(`${p.entryMode === 'relay' ? '经中继' : '直连'}${p.lastAccount ? ' · ' + p.lastAccount : ''}`)
                    .fontSize(this.sm.getFontSize('badge'))
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .margin({ top: 2 })
                }
                .alignItems(HorizontalAlign.Start)
                .layoutWeight(1)

                GlassButton({
                  text: p.id === this.activeId ? '当前' : '使用',
                  type: p.id === this.activeId ? 'primary' : 'default',
                  btnSize: 'small',
                  disabled: this.busy,
                  onTap: () => { this.useProfile(p); }
                })
                GlassButton({
                  text: '删除',
                  type: 'danger',
                  btnSize: 'small',
                  disabled: this.busy,
                  onTap: () => { this.removeProfile(p.id); }
                })
              }
              .width('100%')
              .padding(14)
              .borderRadius(16)
              .margin({ bottom: 10 })
              .backgroundColor(this.sm.getColor('glass'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .alignItems(VerticalAlign.Center)
            }, (p: ServerProfile) => p.id)

            // 新增档案表单（玻璃输入 + 品牌渐变主按钮）
            Column() {
              GlassInput({
                placeholder: '名称（如：家里 / VPS）',
                value: this.newName,
                iconName: 'server',
                onChange: (v: string) => { this.newName = v; }
              })
                .margin({ bottom: 8 })
              GlassInput({
                placeholder: '地址：IP 或中继域名（如 192.168.1.5）',
                value: this.newHost,
                iconName: 'link',
                onChange: (v: string) => { this.newHost = v; }
              })
                .margin({ bottom: 8 })
              Row() {
                GlassInput({
                  placeholder: '端口（如 9527）',
                  value: this.newPort,
                  onChange: (v: string) => { this.newPort = v; }
                })
                  .layoutWeight(1)
                Text('SSL')
                  .fontSize(this.sm.getFontSize('badge'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ left: 12, right: 6 })
                Toggle({ type: ToggleType.Switch, isOn: this.newSsl })
                  .selectedColor(this.sm.getColor('primary'))
                  .onChange((on: boolean) => { this.newSsl = on; })
              }
              .width('100%')
              .margin({ bottom: 8 })
              GlassButton({
                text: '添加 PC 终端',
                type: 'gradient',
                block: true,
                disabled: this.busy,
                onTap: () => { this.addProfile(); }
              })
            }
            .width('100%')
            .padding(14)
            .borderRadius(16)
            .backgroundColor(this.sm.getColor('glass'))
            .border({ width: 1, color: this.sm.getColor('border') })

            Text('切换档案后需用该终端的账号重新登录（账号与令牌不跨终端共享）。')
              .fontSize(this.sm.getFontSize('badge'))
              .fontColor(this.sm.getColor('text_tertiary'))
              .padding(8)
          }
          .width('100%')
          .padding(12)
          .alignItems(HorizontalAlign.Start)
        }
        .layoutWeight(1)
        .scrollBar(BarState.Off)
      }
      .width('100%')
      .height('100%')
    }
    .width('100%')
    .height('100%')
  }
}
