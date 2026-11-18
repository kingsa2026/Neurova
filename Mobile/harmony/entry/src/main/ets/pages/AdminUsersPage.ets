/**
 * AdminUsersPage - 用户管理（管理员，对照原型 F14）
 *
 * 数据：GET /v1/enhanced-users（裸 {items:[UserOut], total}）；
 * 操作：删除（DELETE /{id}，二次确认）；角色徽标随行展示。
 * 门控：路由进此页前由 SettingPage 管理员分组控制 + PROTECTED_ROUTES。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { AdminUserDto } from '../libs/api/modules/AdminApi';

@Component
export struct AdminUsersPage {
  @State private users: AdminUserDto[] = [];
  @State private loading: boolean = false;
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear(): void {
    this.loadUsers();
  }

  private async loadUsers(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.admin.listUsers();
      this.users = res.items;
    } catch (e) {
      this.msg.error('用户列表获取失败：' + (e as Error).message);
    }
    this.loading = false;
  }

  private async remove(u: AdminUserDto): Promise<void> {
    try {
      await this.api.admin.removeUser(u.id);
      this.msg.success('已删除 ' + u.username);
      this.loadUsers();
    } catch (e) {
      this.msg.error('删除失败：' + (e as Error).message);
    }
  }

  private confirmRemove(u: AdminUserDto): void {
    AlertDialog.show({
      title: '删除用户',
      message: '确认删除 ' + u.username + '？该操作不可恢复。',
      autoCancel: true,
      alignment: DialogAlignment.Center,
      buttons: [
        {
          value: '取消',
          action: () => {
          }
        },
        {
          value: '删除',
          fontColor: this.sm.getColor('error'),
          action: () => {
            this.remove(u);
          }
        }
      ]
    });
  }

  build() {
    Column() {
      Row() {
        Text('‹')
          .fontSize(22)
          .fontColor(this.sm.getColor('text_secondary'))
          .padding(8)
          .onClick(() => {
            this.router.back();
          })
        Text('用户管理')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        Text(this.users.length.toString() + ' 人')
          .fontSize(12)
          .fontColor(this.sm.getColor('text_tertiary'))
          .padding(8)
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 6, bottom: 8 })

      Scroll() {
        Column() {
          // 统计卡三联（设计 F14 .adm-stat：用户总数/管理员/成员，均由列表真实派生）
          Row() {
            Column() {
              Text(this.users.length.toString())
                .fontSize(18)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.sm.getColor('text_primary'))
              Text('用户总数')
                .fontSize(10)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 1 })
            }
            .layoutWeight(1)
            .padding({ left: 13, right: 13, top: 10, bottom: 10 })
            .borderRadius(12)
            .backgroundColor(this.sm.getColor('glass'))
            .border({ width: 1, color: this.sm.getColor('border') })
            .alignItems(HorizontalAlign.Start)

            Column() {
              Text(this.users.filter((u: AdminUserDto) => u.role === 'admin').length.toString())
                .fontSize(18)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.sm.getColor('text_primary'))
              Text('管理员')
                .fontSize(10)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 1 })
            }
            .layoutWeight(1)
            .padding({ left: 13, right: 13, top: 10, bottom: 10 })
            .borderRadius(12)
            .backgroundColor(this.sm.getColor('glass'))
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ left: 10 })
            .alignItems(HorizontalAlign.Start)

            Column() {
              Text(this.users.filter((u: AdminUserDto) => u.role !== 'admin').length.toString())
                .fontSize(18)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.sm.getColor('text_primary'))
              Text('成员')
                .fontSize(10)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 1 })
            }
            .layoutWeight(1)
            .padding({ left: 13, right: 13, top: 10, bottom: 10 })
            .borderRadius(12)
            .backgroundColor(this.sm.getColor('glass'))
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ left: 10 })
            .alignItems(HorizontalAlign.Start)
          }
          .width('calc(100% - 40vp)')
          .margin({ left: 20, right: 20, bottom: 12 })
          .alignItems(VerticalAlign.Center)

          if (this.users.length === 0 && !this.loading) {
            Text(this.loading ? '加载中…' : '暂无用户或无权访问')
              .fontSize(13)
              .fontColor(this.sm.getColor('text_tertiary'))
              .margin({ top: 80 })
          }
          ForEach(this.users, (u: AdminUserDto) => {
            Row() {
              Text(u.username.slice(0, 1))
                .fontSize(14)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.sm.getColor('text_on_primary'))
                .width(36)
                .height(36)
                .borderRadius(12)
                .textAlign(TextAlign.Center)
                .backgroundColor(u.role === 'admin' ? this.sm.getColor('primary') : this.sm.getColor('surface_strong'))

              Column() {
                Row() {
                  Text(u.username)
                    .fontSize(13.5)
                    .fontWeight(FontWeight.Medium)
                    .fontColor(this.sm.getColor('text_primary'))
                  Text(u.role === 'admin' ? '管理员' : '成员')
                    .fontSize(9)
                    .fontColor(u.role === 'admin' ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
                    .backgroundColor(u.role === 'admin' ? this.sm.getColor('primary') : this.sm.getColor('surface_strong'))
                    .padding({ left: 6, right: 6, top: 1, bottom: 1 })
                    .borderRadius(5)
                    .margin({ left: 7 })
                }
                Text((u.email.length > 0 ? u.email + ' · ' : '') + (u.last_login.length > 0 ? '最近登录 ' + u.last_login : '未登录'))
                  .fontSize(10.5)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .margin({ top: 3 })
                  .maxLines(1)
                  .textOverflow({ overflow: TextOverflow.Ellipsis })
              }
              .alignItems(HorizontalAlign.Start)
              .layoutWeight(1)
              .margin({ left: 10 })

              Text(u.active ? '活跃' : '停用')
                .fontSize(10)
                .fontColor(u.active ? this.sm.getColor('success') : this.sm.getColor('text_tertiary'))

              Text('⋯')
                .fontSize(15)
                .fontColor(this.sm.getColor('text_tertiary'))
                .padding(6)
                .onClick(() => {
                  this.confirmRemove(u);
                })
            }
            .width('calc(100% - 40vp)')
            .padding(12)
            .borderRadius(13)
            .backgroundColor(this.sm.getColor('glass'))
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ bottom: 8, left: 20, right: 20 })
            .opacity(u.active ? 1 : 0.62)
          }, (u: AdminUserDto) => u.id.toString())
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
