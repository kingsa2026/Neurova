/**
 * AdminMarketPage - 市场管理（管理员，严格按设计稿 F16 还原）
 *
 * 数据：
 *   待审技能  GET /skill-pool/skill-submissions?review_status=pending
 *   待审知识  GET /knowledge/public-submissions（仅管理员；审阅端点后端未提供——只读呈现）
 *   已发布    GET /marketplace/skills + GET /marketplace/installed
 * 操作：审阅 POST /skill-submissions/{id}/review（通过=上架/拒绝=不上架）；
 *       同步市场源 POST /marketplace/sync；上架新技能 POST /marketplace/skills（均仅管理员）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { SubmissionDto } from '../libs/api/modules/AdminApi';
import { MarketSkillDto } from '../libs/api/modules/MarketplaceApi';
import { IconBtn } from '../components/common/IconBtn';
import { AppIcon } from '../components/common/AppIcon';
import { GlassInput } from '../components/glass';

@Component
export struct AdminMarketPage {
  /** 分段：0=待审技能 / 1=待审知识 / 2=已发布（设计 .seg） */
  @State private seg: number = 0;
  @State private skills: SubmissionDto[] = [];
  @State private knowledge: Object[] = [];
  @State private published: MarketSkillDto[] = [];
  @State private installedCount: number = 0;
  @State private loading: boolean = false;
  @State private busy: boolean = false;
  // 上架弹层
  @State private publishing: boolean = false;
  @State private pubId: string = '';
  @State private pubName: string = '';
  @State private pubDesc: string = '';
  // 已安装清单弹层
  @State private installedOpen: boolean = false;
  @State private installedNames: string[] = [];
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear(): void {
    this.loadAll();
  }

  private async loadAll(): Promise<void> {
    this.loading = true;
    await this.loadSkills();
    await this.loadKnowledge();
    await this.loadPublished();
    this.loading = false;
  }

  private async loadSkills(): Promise<void> {
    try {
      const res = await this.api.admin.pendingSubmissions();
      if (res.code === 0 && res.data) {
        this.skills = res.data.items;
      }
    } catch (e) {
      this.msg.error('待审技能获取失败：' + (e as Error).message);
    }
  }

  private async loadKnowledge(): Promise<void> {
    try {
      const res = await this.api.admin.publicSubmissions();
      if (res.code === 0 && res.data) {
        this.knowledge = res.data;
      }
    } catch (e) {
      // 403 等如实静默（分段计数显示 0，不阻塞技能审阅面）
      this.knowledge = [];
    }
  }

  private async loadPublished(): Promise<void> {
    try {
      const res = await this.api.marketplace.list({ limit: 100, offset: 0 });
      if (res.code === 0 && res.data) {
        this.published = res.data.items;
      }
      const inst = await this.api.marketplace.installed();
      if (inst.code === 0 && inst.data) {
        this.installedCount = inst.data.length;
      }
    } catch (e) {
      this.msg.error('已发布清单获取失败：' + (e as Error).message);
    }
  }

  private async review(s: SubmissionDto, approve: boolean): Promise<void> {
    this.busy = true;
    try {
      const res = await this.api.admin.reviewSubmission(s.id, approve, '');
      if (res.code === 0) {
        this.msg.success(approve ? '已通过并上架市场' : '已拒绝');
        this.loadSkills();
      } else {
        this.msg.error(res.message || '审阅失败');
      }
    } catch (e) {
      this.msg.error('审阅失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  private async syncSources(): Promise<void> {
    this.busy = true;
    try {
      const res = await this.api.marketplace.sync();
      if (res.code === 0) {
        this.msg.success('市场源已同步');
        this.loadPublished();
      } else {
        this.msg.error(res.message || '同步失败');
      }
    } catch (e) {
      this.msg.error('同步失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  private async publishSkill(): Promise<void> {
    if (this.pubId.trim().length === 0 || this.pubName.trim().length === 0) {
      this.msg.warning('技能 ID 与名称不能为空');
      return;
    }
    this.busy = true;
    try {
      const res = await this.api.marketplace.publish({
        skillId: this.pubId.trim(),
        name: this.pubName.trim(),
        description: this.pubDesc.trim(),
        author: 'admin',
        version: '1.0.0',
        category: 'general',
        downloadUrl: '',
      });
      if (res.code === 0) {
        this.msg.success('已上架市场');
        this.publishing = false;
        this.loadPublished();
      } else {
        this.msg.error(res.message || '上架失败');
      }
    } catch (e) {
      this.msg.error('上架失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  private async openInstalled(): Promise<void> {
    try {
      const res = await this.api.marketplace.installed();
      if (res.code === 0 && res.data) {
        this.installedNames = res.data.map((s: MarketSkillDto) => s.name);
        this.installedOpen = true;
      }
    } catch (e) {
      this.msg.error('已安装清单获取失败：' + (e as Error).message);
    }
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

  /** 知识投稿条目标题（KnowledgeItem 形状，取 title 回退 id） */
  private knowledgeTitle(item: Object): string {
    const rec = item as Record<string, Object>;
    const t = rec['title'];
    if (typeof t === 'string' && t.length > 0) {
      return t;
    }
    const id = rec['id'];
    return typeof id === 'string' ? id : '知识投稿';
  }

  /** 分段胶囊（设计 .sg；标签在 builder 内读 State——@Builder 按值参数不刷新） */
  @Builder
  segPill(idx: number) {
    Text(this.segLabel(idx))
      .fontSize(12)
      .padding({ left: 14, right: 14, top: 6, bottom: 6 })
      .borderRadius(999)
      .fontColor(this.seg === idx ? '#FFFFFF' : this.sm.getColor('text_secondary'))
      .backgroundColor(this.seg === idx ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
      .border({ width: 1, color: this.seg === idx ? 'rgba(99,102,241,0.50)' : this.sm.getColor('border') })
      .margin({ left: idx > 0 ? 6 : 0 })
      .onClick(() => { this.seg = idx; })
  }

  private segLabel(idx: number): string {
    if (idx === 0) {
      return '待审技能 ' + this.skills.length.toString();
    }
    if (idx === 1) {
      return '待审知识 ' + this.knowledge.length.toString();
    }
    return '已发布 ' + this.published.length.toString();
  }

  /** 审阅卡（设计 .rv-card：标题+类型徽标 / 提交人行 / 通过-拒绝） */
  @Builder
  reviewCard(s: SubmissionDto, title: string, typeLabel: string, subLine: string) {
    Column() {
      Row() {
        Text(title)
          .fontSize(13.5)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(typeLabel)
          .fontSize(10)
          .fontColor(this.sm.getColor('primary'))
          .padding({ left: 6, right: 6, top: 2, bottom: 2 })
          .borderRadius(6)
          .backgroundColor(this.sm.getColor('primary_soft'))
          .border({ width: 1, color: this.sm.getColor('primary') })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(subLine)
        .fontSize(11)
        .fontColor(this.sm.getColor('text_secondary'))
        .margin({ top: 4 })
        .width('100%')

      Row() {
        Row() {
          AppIcon({ name: 'check', iconSize: 12, color: this.sm.getColor('success') })
          Text('通过')
            .fontSize(12)
            .fontColor(this.sm.getColor('success'))
            .margin({ left: 4 })
        }
        .layoutWeight(1)
        .height(34)
        .justifyContent(FlexAlign.Center)
        .borderRadius(10)
        .backgroundColor('rgba(52,211,153,0.10)')
        .border({ width: 1, color: 'rgba(52,211,153,0.35)' })
        .opacity(this.busy ? 0.5 : 1)
        .onClick(() => { this.review(s, true); })

        Row() {
          AppIcon({ name: 'stop', iconSize: 12, color: this.sm.getColor('error') })
          Text('拒绝')
            .fontSize(12)
            .fontColor(this.sm.getColor('error'))
            .margin({ left: 4 })
        }
        .layoutWeight(1)
        .height(34)
        .justifyContent(FlexAlign.Center)
        .borderRadius(10)
        .backgroundColor(this.sm.getColor('surface_strong'))
        .border({ width: 1, color: 'rgba(248,113,113,0.40)' })
        .margin({ left: 9 })
        .opacity(this.busy ? 0.5 : 1)
        .onClick(() => { this.review(s, false); })
      }
      .width('100%')
      .margin({ top: 10 })
    }
    .width('calc(100% - 40vp)')
    .padding(13)
    .borderRadius(16)
    .backgroundColor(this.sm.getColor('glass'))
    .border({ width: 1, color: this.sm.getColor('border') })
    .margin({ bottom: 10, left: 20, right: 20 })
  }

  build() {
    Stack() {
      Column() {
        // 头部（设计 .phead：返回 + 市场管理）
        Row() {
          IconBtn({ name: 'back', onTap: () => { this.router.back(); } })
          Text('市场管理')
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
            // 分段（设计 .seg：待审技能 / 待审知识 / 已发布）
            Row() {
              this.segPill(0)
              this.segPill(1)
              this.segPill(2)
              Blank()
            }
            .width('100%')
            .padding({ left: 20, right: 20, bottom: 12 })

            if (this.seg === 0) {
              if (this.skills.length === 0 && !this.loading) {
                Text('暂无待审技能投稿')
                  .fontSize(13)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .margin({ top: 60 })
              }
              ForEach(this.skills, (s: SubmissionDto) => {
                this.reviewCard(s, this.titleOf(s), '技能',
                  (s.username.length > 0 ? '提交人 ' + s.username : '匿名提交') +
                  (s.submitted_at.length > 0 ? ' · ' + s.submitted_at.slice(0, 10) : ''))
              }, (s: SubmissionDto) => s.id)
            } else if (this.seg === 1) {
              if (this.knowledge.length === 0 && !this.loading) {
                Text('暂无待审知识投稿')
                  .fontSize(13)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .margin({ top: 60 })
              }
              ForEach(this.knowledge, (item: Object, idx: number) => {
                Column() {
                  Row() {
                    Text(this.knowledgeTitle(item))
                      .fontSize(13.5)
                      .fontWeight(FontWeight.Medium)
                      .fontColor(this.sm.getColor('text_primary'))
                      .layoutWeight(1)
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                    Text('知识')
                      .fontSize(10)
                      .fontColor(this.sm.getColor('primary'))
                      .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                      .borderRadius(6)
                      .backgroundColor(this.sm.getColor('primary_soft'))
                      .border({ width: 1, color: this.sm.getColor('primary') })
                  }
                  .width('100%')
                  .alignItems(VerticalAlign.Center)
                  Text('公共库投稿 · 审阅端点后端未提供，裁决在 PC 治理页完成')
                    .fontSize(10.5)
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .margin({ top: 4 })
                }
                .width('calc(100% - 40vp)')
                .padding(13)
                .borderRadius(16)
                .backgroundColor(this.sm.getColor('glass'))
                .border({ width: 1, color: this.sm.getColor('border') })
                .margin({ bottom: 10, left: 20, right: 20 })
              }, (item: Object, idx: number) => idx.toString())
            } else {
              // 已发布 · 管理操作（设计 .sec-t + .me-grp）
              Row() {
                Text('已发布 · 管理操作')
                  .fontSize(12.5)
                  .fontWeight(FontWeight.Medium)
                  .fontColor(this.sm.getColor('text_primary'))
              }
              .width('calc(100% - 40vp)')
              .padding({ left: 4, bottom: 8 })

              Column() {
                Row() {
                  AppIcon({ name: 'link', iconSize: 14, color: this.sm.getColor('secondary') })
                  Text('同步市场源')
                    .fontSize(13)
                    .fontColor(this.sm.getColor('text_primary'))
                    .margin({ left: 10 })
                    .layoutWeight(1)
                  Text(this.busy ? '同步中…' : '')
                    .fontSize(11)
                    .fontColor(this.sm.getColor('text_tertiary'))
                  AppIcon({ name: 'chev', iconSize: 12, color: this.sm.getColor('text_tertiary') })
                }
                .width('100%')
                .padding({ top: 11, bottom: 11 })
                .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
                .alignItems(VerticalAlign.Center)
                .onClick(() => { this.syncSources(); })

                Row() {
                  AppIcon({ name: 'plus', iconSize: 14, color: this.sm.getColor('secondary') })
                  Text('发布新技能')
                    .fontSize(13)
                    .fontColor(this.sm.getColor('text_primary'))
                    .margin({ left: 10 })
                    .layoutWeight(1)
                  AppIcon({ name: 'chev', iconSize: 12, color: this.sm.getColor('text_tertiary') })
                }
                .width('100%')
                .padding({ top: 11, bottom: 11 })
                .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
                .alignItems(VerticalAlign.Center)
                .onClick(() => { this.publishing = true; })

                Row() {
                  AppIcon({ name: 'folder', iconSize: 14, color: this.sm.getColor('secondary') })
                  Text('已安装清单')
                    .fontSize(13)
                    .fontColor(this.sm.getColor('text_primary'))
                    .margin({ left: 10 })
                    .layoutWeight(1)
                  Text(this.installedCount.toString() + ' 项')
                    .fontSize(11)
                    .fontColor(this.sm.getColor('text_tertiary'))
                  AppIcon({ name: 'chev', iconSize: 12, color: this.sm.getColor('text_tertiary') })
                    .margin({ left: 4 })
                }
                .width('100%')
                .padding({ top: 11, bottom: 11 })
                .alignItems(VerticalAlign.Center)
                .onClick(() => { this.openInstalled(); })
              }
              .width('calc(100% - 40vp)')
              .padding({ left: 15, right: 15 })
              .borderRadius(16)
              .backgroundColor(this.sm.getColor('glass'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .margin({ left: 20, right: 20, bottom: 12 })

              // 已发布技能列表（紧凑）
              ForEach(this.published, (s: MarketSkillDto) => {
                Row() {
                  Text(s.name)
                    .fontSize(12.5)
                    .fontColor(this.sm.getColor('text_primary'))
                    .layoutWeight(1)
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                  Text('v' + s.version)
                    .fontSize(10.5)
                    .fontFamily(this.sm.getMonoFont())
                    .fontColor(this.sm.getColor('text_tertiary'))
                  Text(s.installed ? '已装' : '')
                    .fontSize(10)
                    .fontColor(this.sm.getColor('success'))
                    .margin({ left: 6 })
                }
                .width('calc(100% - 40vp)')
                .padding({ left: 15, right: 15, top: 10, bottom: 10 })
                .borderRadius(12)
                .backgroundColor(this.sm.getColor('glass'))
                .border({ width: 1, color: this.sm.getColor('border') })
                .margin({ bottom: 8, left: 20, right: 20 })
              }, (s: MarketSkillDto) => s.skill_id)
            }
          }
          .width('100%')
          .padding({ bottom: 20 })
        }
        .layoutWeight(1)
        .scrollBar(BarState.Off)
        .width('100%')
      }
      .width('100%')
      .height('100%')

      // 上架弹层
      if (this.publishing) {
        Column() {
          Column() {
            Text('发布新技能')
              .fontSize(15)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
            GlassInput({
              placeholder: '技能 ID（如 weekly_report）',
              value: this.pubId,
              onChange: (v: string) => { this.pubId = v; }
            })
              .margin({ top: 12 })
            GlassInput({
              placeholder: '技能名称',
              value: this.pubName,
              onChange: (v: string) => { this.pubName = v; }
            })
              .margin({ top: 10 })
            GlassInput({
              placeholder: '简介（可空）',
              value: this.pubDesc,
              onChange: (v: string) => { this.pubDesc = v; }
            })
              .margin({ top: 10 })
            Row() {
              Text('取消')
                .fontSize(13)
                .fontColor(this.sm.getColor('text_secondary'))
                .padding({ left: 14, right: 14, top: 8, bottom: 8 })
                .onClick(() => { this.publishing = false; })
              Text(this.busy ? '提交中…' : '上架')
                .fontSize(13)
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_on_primary'))
                .padding({ left: 16, right: 16, top: 8, bottom: 8 })
                .borderRadius(10)
                .linearGradient({ angle: 135, colors: this.sm.getBrandGradient() })
                .margin({ left: 8 })
                .onClick(() => { this.publishSkill(); })
            }
            .width('100%')
            .justifyContent(FlexAlign.End)
            .margin({ top: 14 })
          }
          .width('82%')
          .padding(16)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface_strong'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .height('100%')
        .backgroundColor('rgba(4,6,14,0.60)')
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      }

      // 已安装清单弹层
      if (this.installedOpen) {
        Column() {
          Column() {
            Text('已安装清单 · ' + this.installedNames.length.toString() + ' 项')
              .fontSize(15)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ bottom: 8 })
            Scroll() {
              Column() {
                ForEach(this.installedNames, (n: string) => {
                  Text(n)
                    .fontSize(12.5)
                    .fontColor(this.sm.getColor('text_secondary'))
                    .padding({ top: 6, bottom: 6 })
                    .width('100%')
                }, (n: string) => n)
              }
              .width('100%')
              .alignItems(HorizontalAlign.Start)
            }
            .height(220)
            .scrollBar(BarState.Off)
            Text('收起')
              .fontSize(12.5)
              .fontColor(this.sm.getColor('primary'))
              .padding({ top: 10 })
              .onClick(() => { this.installedOpen = false; })
          }
          .width('76%')
          .padding(16)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface_strong'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .height('100%')
        .backgroundColor('rgba(4,6,14,0.60)')
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
