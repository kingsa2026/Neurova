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
      await this.store.add(this.newName, this.newUrl);
      this.newName = '';
      this.newUrl = '';
      this.refresh();
      this.msg.success('档案已添加');
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
    Column() {
      Row() {
        Text('<').fontSize(20).onClick(() => this.router.back()).margin({ right: 12 })
        Text('服务器档案').fontSize(20).fontWeight(FontWeight.Bold)
      }.width('100%').padding(16)

      Scroll() {
        Column() {
          ForEach(this.profiles, (p: ServerProfile) => {
            Column() {
              Row() {
                Column() {
                  Text(p.name).fontSize(16).fontWeight(FontWeight.Medium)
                  Text(p.baseUrl).fontSize(12).opacity(0.7).margin({ top: 2 })
                  Text(`${p.entryMode === 'relay' ? '经中继' : '直连'}${p.lastAccount ? ' · ' + p.lastAccount : ''}`)
                    .fontSize(11).opacity(0.6).margin({ top: 2 })
                }.alignItems(HorizontalAlign.Start).layoutWeight(1)

                Button(p.id === this.activeId ? '当前' : '使用')
                  .fontSize(12)
                  .backgroundColor(p.id === this.activeId ? '#34d399' : '#5b8cff')
                  .onClick(() => this.useProfile(p))
                Button('删')
                  .fontSize(12)
                  .backgroundColor('#f87171')
                  .margin({ left: 6 })
                  .onClick(() => this.removeProfile(p.id))
              }.width('100%')
            }.padding(12).borderRadius(12).margin({ bottom: 10 }).backgroundColor('#161c29')
          }, (p: ServerProfile) => p.id)

          Column() {
            TextInput({ placeholder: '名称（如：家里 / VPS）' })
              .onChange((v: string) => { this.newName = v; })
              .margin({ bottom: 8 })
            TextInput({ placeholder: 'http://192.168.x.x:9527 或 https://中继/t/routeId' })
              .onChange((v: string) => { this.newUrl = v; })
              .margin({ bottom: 8 })
            Button('添加服务器档案').width('100%').onClick(() => this.addProfile())
          }.padding(12).borderRadius(12).backgroundColor('#161c29')

          Text('切换档案后需用该服务器的账号重新登录（账号与令牌不跨服务器共享）。')
            .fontSize(11).opacity(0.6).padding(8)
        }.width('100%').padding(12)
      }.layoutWeight(1).scrollBar(BarState.Off)
    }.width('100%').height('100%').backgroundColor('#0b0e14')
  }
}
