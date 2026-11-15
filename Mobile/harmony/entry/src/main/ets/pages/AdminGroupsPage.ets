/**
 * AdminGroupsPage - 用户组管理（管理员，对照原型 F15）
 *
 * 数据：GET /v1/groups（裸数组 GroupInfo：group_id/name/description/members_count）；
 * 操作：新建组（POST /groups，GroupCreate {name, description}）。
 * 模块权限（allowed_modules）与成员编辑在 PC 端组页管理——移动端只读 + 建组。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { AdminGroupDto } from '../libs/api/modules/AdminApi';

@Component
export struct AdminGroupsPage {
  @State private groups: AdminGroupDto[] = [];
  @State private loading: boolean = false;
  @State private showCreate: boolean = false;
  @State private newName: string = '';
  @State private newDesc: string = '';
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear(): void {
    this.loadGroups();
  }

  private async loadGroups(): Promise<void> {
    this.loading = true;
    try {
      this.groups = await this.api.admin.listGroups();
    } catch (e) {
      this.msg.error('用户组获取失败：' + (e as Error).message);
    }
    this.loading = false;
  }

  private async createGroup(): Promise<void> {
    if (this.newName.trim().length === 0) {
      this.msg.warning('组名不能为空');
      return;
    }
    try {
      await this.api.admin.createGroup(this.newName.trim(), this.newDesc.trim());
      this.msg.success('已创建 ' + this.newName.trim());
      this.showCreate = false;
      this.newName = '';
      this.newDesc = '';
      this.loadGroups();
    } catch (e) {
      this.msg.error('创建失败：' + (e as Error).message);
    }
  }

  build() {
    Stack() {
      Column() {
        Row() {
          Text('‹')
            .fontSize(22)
            .fontColor(this.sm.getColor('text_secondary'))
            .padding(8)
            .onClick(() => {
              this.router.back();
            })
          Text('用户组')
            .fontSize(17)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .textAlign(TextAlign.Center)
          Text('＋ 建组')
            .fontSize(13)
            .fontColor(this.sm.getColor('primary'))
            .padding(8)
            .onClick(() => {
              this.showCreate = true;
            })
        }
        .width('100%')
        .padding({ left: 12, right: 12, top: 6, bottom: 8 })

        Scroll() {
          Column() {
            if (this.groups.length === 0 && !this.loading) {
              Text(this.loading ? '加载中…' : '暂无用户组')
                .fontSize(13)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 80 })
            }
            ForEach(this.groups, (g: AdminGroupDto) => {
              Column() {
                Row() {
                  Text(g.name)
                    .fontSize(14)
                    .fontWeight(FontWeight.Medium)
                    .fontColor(this.sm.getColor('text_primary'))
                  Text(g.members_count.toString() + ' 名成员')
                    .fontSize(10)
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .margin({ left: 8 })
                  Blank()
                  Text('›')
                    .fontSize(14)
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .opacity(0.5)
                }
                .width('100%')

                if (g.description.length > 0) {
                  Text(g.description)
                    .fontSize(11.5)
                    .fontColor(this.sm.getColor('text_secondary'))
                    .margin({ top: 5 })
                }
                Row() {
                  ForEach(g.members.slice(0, 5), (m: string) => {
                    Text(m.slice(0, 1))
                      .fontSize(10)
                      .fontColor(this.sm.getColor('text_on_primary'))
                      .width(24)
                      .height(24)
                      .borderRadius(12)
                      .textAlign(TextAlign.Center)
                      .backgroundColor(this.sm.getColor('primary'))
                      .margin({ right: 4 })
                      .border({ width: 2, color: this.sm.getColor('surface') })
                  }, (m: string) => m)
                }
                .margin({ top: 10 })
              }
              .width('calc(100% - 40vp)')
              .padding(14)
              .borderRadius(16)
              .backgroundColor(this.sm.getColor('surface'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .margin({ bottom: 10, left: 20, right: 20 })
            }, (g: AdminGroupDto) => g.group_id)
          }
          .width('100%')
        }
        .layoutWeight(1)
        .scrollBar(BarState.Off)
        .width('100%')
      }
      .width('100%')
      .height('100%')

      // 建组浮层
      if (this.showCreate) {
        Column() {
          Column() {
            Text('新建用户组')
              .fontSize(16)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ bottom: 12 })
            TextInput({ placeholder: '组名' })
              .onChange((v: string) => {
                this.newName = v;
              })
              .height(42)
              .borderRadius(12)
              .backgroundColor(this.sm.getColor('surface_strong'))
            TextInput({ placeholder: '描述（可选）' })
              .onChange((v: string) => {
                this.newDesc = v;
              })
              .height(42)
              .borderRadius(12)
              .backgroundColor(this.sm.getColor('surface_strong'))
              .margin({ top: 9 })
            Row() {
              Button('取消')
                .layoutWeight(1)
                .height(40)
                .backgroundColor(this.sm.getColor('surface_strong'))
                .fontColor(this.sm.getColor('text_secondary'))
                .onClick(() => {
                  this.showCreate = false;
                })
              Button('创建')
                .layoutWeight(1)
                .height(40)
                .backgroundColor(this.sm.getColor('primary'))
                .fontColor(this.sm.getColor('text_on_primary'))
                .margin({ left: 10 })
                .onClick(() => {
                  this.createGroup();
                })
            }
            .width('100%')
            .margin({ top: 16 })
          }
          .width('84%')
          .padding(20)
          .borderRadius(18)
          .backgroundColor(this.sm.getColor('surface'))
          .border({ width: 1, color: this.sm.getColor('border') })
        }
        .width('100%')
        .height('100%')
        .justifyContent(FlexAlign.Center)
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => {
          this.showCreate = false;
        })
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
