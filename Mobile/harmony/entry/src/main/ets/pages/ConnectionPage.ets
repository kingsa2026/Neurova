/**
 * ConnectionPage - 服务器档案「连接」页（设计方案 §6.4 第 2 条，已裁 D4 多档案）
 *
 * 职责：列出/新增/切换/删除服务器档案；切换后把地址落到 HTTP 装配点
 *       （ConfigManager.applyServerProfile），并要求以该服务器账号重新登录。
 *
 * 设计：简化 ArkUI 列表页（List + TextInput），样式 token 走 StyleManager；
 *       服务器地址不写死，全部来自本页档案。
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

const TAG = 'ConnectionPage';

@Entry
@Component
export struct ConnectionPage {
  @State profiles: ServerProfile[] = [];
  @State activeId: string = '';
  @State newUrl: string = '';
  @State newName: string = '';
  @State busy: boolean = false;

  private store = ServerProfiles.getInstance();
  private cm = ConfigManager.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.refresh();
  }

  private refresh(): void {
    this.profiles = this.store.getList();
    const active = this.store.getActive();
    this.activeId = active ? active.id : '';
  }

  /** 切换档案：地址落 HTTP 装配点；要求以该服务器账号重新登录 */
  private async useProfile(p: ServerProfile): Promise<void> {
    this.busy = true;
    try {
      await this.store.switchTo(p.id);
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
    if (!this.newUrl || this.newUrl.length < 7) {
      this.msg.warning('请输入有效的服务器地址');
      return;
    }
    this.busy = true;
    try {
      const added = await this.store.add(this.newName, this.newUrl);
      this.newName = '';
      this.newUrl = '';
      // 新档案立即激活并进入扫码配对：二维码只带 ref 不带地址（§3.4），
      // 所以先录地址、再扫码配对，两步缺一不可
      await this.store.switchTo(added.id);
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
      await this.store.remove(id);
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
          Text('服务器档案')
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
                placeholder: 'http://192.168.x.x:9527 或 https://中继/t/routeId',
                value: this.newUrl,
                iconName: 'link',
                onChange: (v: string) => { this.newUrl = v; }
              })
                .margin({ bottom: 8 })
              GlassButton({
                text: '添加服务器档案',
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

            Text('切换档案后需用该服务器的账号重新登录（账号与令牌不跨服务器共享）。')
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
