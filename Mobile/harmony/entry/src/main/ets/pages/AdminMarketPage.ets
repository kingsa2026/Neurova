/**
 * AdminMarketPage - 市场管理（管理员，对照原型 F16）
 *
 * 数据：GET /v1/skill-pool/skill-submissions?review_status=pending
 *       （{code:0,data:{items,total}}，条目为提交存储的防御性子集）；
 * 操作：审阅 POST /skill-submissions/{id}/review（SkillSubmissionReview
 *       {approve:bool, note}——approve 上架市场 / reject 不上架）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { SubmissionDto } from '../libs/api/modules/AdminApi';

@Component
export struct AdminMarketPage {
  @State private items: SubmissionDto[] = [];
  @State private loading: boolean = false;
  @State private busy: boolean = false;
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear(): void {
    this.loadPending();
  }

  private async loadPending(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.admin.pendingSubmissions();
      if (res.code === 0 && res.data) {
        this.items = res.data.items;
      } else {
        this.msg.error(res.message || '待审投稿获取失败');
      }
    } catch (e) {
      this.msg.error('待审投稿获取失败：' + (e as Error).message);
    }
    this.loading = false;
  }

  private async review(s: SubmissionDto, approve: boolean): Promise<void> {
    this.busy = true;
    try {
      const res = await this.api.admin.reviewSubmission(s.id, approve, '');
      if (res.code === 0) {
        this.msg.success(approve ? '已通过并上架市场' : '已拒绝');
        this.loadPending();
      } else {
        this.msg.error(res.message || '审阅失败');
      }
    } catch (e) {
      this.msg.error('审阅失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  private titleOf(s: SubmissionDto): string {
    if (s.title.length > 0) {
      return s.title;
    }
    if (s.skill_name.length > 0) {
      return s.skill_name;
    }
    return s.id;
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
        Text('市场管理')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        Text(this.items.length.toString() + ' 待审')
          .fontSize(12)
          .fontColor(this.sm.getColor('warning'))
          .padding(8)
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 6, bottom: 8 })

      Scroll() {
        Column() {
          if (this.items.length === 0 && !this.loading) {
            Column() {
              Text('暂无待审投稿')
                .fontSize(14)
                .fontColor(this.sm.getColor('text_tertiary'))
              Text('技能 / 知识投稿提交后会出现在这里')
                .fontSize(12)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 6 })
            }
            .width('100%')
            .margin({ top: 90 })
          }
          ForEach(this.items, (s: SubmissionDto) => {
            Column() {
              Text(this.titleOf(s))
                .fontSize(13.5)
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_primary'))
              Text((s.username.length > 0 ? '提交人 ' + s.username : '匿名提交') +
                (s.submitted_at.length > 0 ? ' · ' + s.submitted_at.slice(0, 10) : ''))
                .fontSize(11)
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ top: 4 })

              Row() {
                Button('通过')
                  .layoutWeight(1)
                  .height(34)
                  .fontSize(12)
                  .backgroundColor(this.sm.getColor('success'))
                  .fontColor(this.sm.getColor('text_on_primary'))
                  .enabled(!this.busy)
                  .onClick(() => {
                    this.review(s, true);
                  })
                Button('拒绝')
                  .layoutWeight(1)
                  .height(34)
                  .fontSize(12)
                  .backgroundColor(this.sm.getColor('surface_strong'))
                  .fontColor(this.sm.getColor('error'))
                  .border({ width: 1, color: this.sm.getColor('error') })
                  .margin({ left: 9 })
                  .enabled(!this.busy)
                  .onClick(() => {
                    this.review(s, false);
                  })
              }
              .width('100%')
              .margin({ top: 10 })
            }
            .width('calc(100% - 40vp)')
            .padding(13)
            .borderRadius(16)
            .backgroundColor(this.sm.getColor('surface'))
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ bottom: 10, left: 20, right: 20 })
          }, (s: SubmissionDto) => s.id)
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
