/**
 * AdminEvolutionPage - 演化状态（管理员域，只读；P1-8）
 *
 * 接 P1-5 世代治理端点（EvolutionApi，与 PC RsiGovernancePage 同源同批端点）：
 * 当前基线代、最近世代列表（状态徽标）、最近一代门禁结果摘要（G0-G4 三态）。
 * 范围纪律（P1-8）：移动端只读呈现——审批/参数修改等写面留在 PC 治理页。
 * 诚实纪律（教义第 2 条）：503 未装配 / 404 无基线代按后端原因原文展示，
 * 不折成空列表冒充正常；门禁三态（通过/未过/无证据）分色分文，不折叠。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { IconBtn } from '../components/common/IconBtn';
import { AppIcon } from '../components/common/AppIcon';
import { StatusPill } from '../components/common/StatusPill';
import {
  EvolutionGenerationDto,
  EvolutionGenerationSummaryDto,
  EVOLUTION_VERDICT_KEYS,
} from '../libs/api/modules/EvolutionApi';

/** 世代状态 → 中文标签（未知值诚实保留原值） */
function statusLabelOf(status: string): string {
  if (status === 'proposed') { return '已立案'; }
  if (status === 'shadowTesting') { return '影子验证中'; }
  if (status === 'gated') { return '门禁完成'; }
  if (status === 'canary') { return '金丝雀观测中'; }
  if (status === 'deployed') { return '已部署'; }
  if (status === 'rejected') { return '已拒绝'; }
  if (status === 'rolledBack') { return '已回滚'; }
  return status;
}

/** 世代状态 → StatusPill 变体（deployed 绿 / 观测中黄 / 终态败红 / 其余中性） */
function statusVariantOf(status: string): string {
  if (status === 'deployed') { return 'run'; }
  if (status === 'canary' || status === 'shadowTesting') { return 'queue'; }
  if (status === 'rejected' || status === 'rolledBack') { return 'err'; }
  return 'done';
}

/** 门禁三态 → 中文标签（unevidenced 与 failed 分文——"没证据"不冒充"未过"） */
function verdictLabelOf(state: string): string {
  if (state === 'passed') { return '通过'; }
  if (state === 'failed') { return '未过'; }
  return '无证据';
}

/** 门禁三态 → StatusPill 变体 */
function verdictVariantOf(state: string): string {
  if (state === 'passed') { return 'run'; }
  if (state === 'failed') { return 'err'; }
  return 'queue';
}

/** 裁决 → 一行文案（审批人/理由随行，缺失不编造） */
function decisionLabelOf(kind: string, approver: string, reason: string): string {
  if (kind === 'approval') { return '人工审批' + (approver.length > 0 ? ' · ' + approver : ''); }
  if (kind === 'rejected') { return '已否决' + (reason.length > 0 ? ' · ' + reason : ''); }
  if (kind === 'auto') { return '自动'; }
  return kind.length > 0 ? kind : '未裁决';
}

@Component
export struct AdminEvolutionPage {
  @State private baseline: EvolutionGenerationDto | null = null;
  @State private baselineNote: string = '';
  @State private generations: EvolutionGenerationSummaryDto[] = [];
  @State private latestDetail: EvolutionGenerationDto | null = null;
  @State private loading: boolean = false;
  @State private errorText: string = '';
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    this.loading = true;
    this.errorText = '';
    this.baselineNote = '';
    // 世代列表 + 最近一代门禁摘要
    try {
      const listRes = await this.api.evolution.listGenerations(10);
      if (listRes.code === 0 && listRes.data) {
        this.generations = listRes.data.generations;
        this.latestDetail = null;
        if (this.generations.length > 0) {
          const detailRes = await this.api.evolution.generationDetail(this.generations[0].generationNo);
          this.latestDetail = detailRes.code === 0 && detailRes.data ? detailRes.data : null;
        }
      } else {
        this.generations = [];
        this.latestDetail = null;
        this.errorText = listRes.message && listRes.message.length > 0 ? listRes.message : '世代列表获取失败';
      }
    } catch (e) {
      this.generations = [];
      this.latestDetail = null;
      this.errorText = '世代列表获取失败：' + (e as Error).message;
    }
    // 当前基线代：404 是诚实事实（尚无 deployed 代），单独呈现，不当错误横幅
    try {
      const baseRes = await this.api.evolution.currentBaseline();
      if (baseRes.code === 0 && baseRes.data) {
        this.baseline = baseRes.data;
      } else {
        this.baseline = null;
        this.baselineNote = baseRes.message && baseRes.message.length > 0 ? baseRes.message : '尚无已部署的生产基线代';
      }
    } catch (e) {
      this.baseline = null;
      this.baselineNote = '当前基线代获取失败：' + (e as Error).message;
    }
    this.loading = false;
  }

  /** 门禁键规范序（g0..g4）在前、非规范键诚实追在后的摘要键序 */
  private verdictKeys(): string[] {
    if (this.latestDetail === null) {
      return [];
    }
    const out: string[] = [];
    for (const k of EVOLUTION_VERDICT_KEYS) {
      if (this.latestDetail.verdicts[k] !== undefined) {
        out.push(k);
      }
    }
    for (const k of Object.keys(this.latestDetail.verdicts)) {
      if (out.indexOf(k) === -1) {
        out.push(k);
      }
    }
    return out;
  }

  /** 分组标签（对齐 AdminSettingsPage .grp-lab 形态） */
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
      // 头部：返回 + 标题
      Row() {
        IconBtn({ name: 'back', onTap: () => { this.router.back(); } })
        Text('演化状态')
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
          this.groupLabel('spark', '当前基线代')

          // 当前基线代卡：404 如实说"尚无"，不拿最大序号充数
          Column() {
            if (this.baseline !== null) {
              Row() {
                Text('#' + this.baseline.generationNo.toString())
                  .fontSize(20)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.sm.getColor('text_primary'))
                StatusPill({ variant: statusVariantOf(this.baseline.status), text: statusLabelOf(this.baseline.status) })
                  .margin({ left: 10 })
              }
              .width('100%')
              .alignItems(VerticalAlign.Center)
              if (this.baseline.deployment !== null && this.baseline.deployment.promotedAt.length > 0) {
                Text('晋升时间：' + this.baseline.deployment.promotedAt)
                  .fontSize(11.5)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .margin({ top: 6 })
              }
              if (this.baseline.basisCommit.length > 0) {
                Text('基线 commit：' + this.baseline.basisCommit)
                  .fontSize(11.5)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .margin({ top: 3 })
                  .maxLines(1)
              }
            } else {
              Text(this.loading ? '加载中…' : (this.baselineNote.length > 0 ? this.baselineNote : '尚无已部署的生产基线代'))
                .fontSize(12.5)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 4, bottom: 4 })
            }
          }
          .width('calc(100% - 40vp)')
          .padding({ left: 15, right: 15, top: 10, bottom: 12 })
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ left: 20, right: 20, bottom: 6 })

          this.groupLabel('task', '最近世代')

          // 最近世代列表卡（limit 10；列表为空与未装配分开呈现）
          Column() {
            if (this.errorText.length > 0) {
              Text('世代读面不可用：' + this.errorText)
                .fontSize(12.5)
                .fontColor(this.sm.getColor('error'))
                .margin({ top: 6, bottom: 6 })
            } else if (this.generations.length === 0) {
              Text(this.loading ? '加载中…' : '没有世代记录（账本空；这与"未装配"是两回事）')
                .fontSize(12.5)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 6, bottom: 6 })
            }
            ForEach(this.generations, (gen: EvolutionGenerationSummaryDto) => {
              Row() {
                Text('#' + gen.generationNo.toString() + (gen.parentNo !== null ? ' ← #' + gen.parentNo.toString() : ''))
                  .fontSize(13)
                  .fontWeight(FontWeight.Medium)
                  .fontColor(this.sm.getColor('text_primary'))
                  .layoutWeight(1)
                StatusPill({ variant: statusVariantOf(gen.status), text: statusLabelOf(gen.status) })
                Text(gen.promotedAt.length > 0 ? gen.promotedAt : '—')
                  .fontSize(10.5)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .margin({ left: 8 })
                  .maxLines(1)
              }
              .width('100%')
              .padding({ top: 9, bottom: 9 })
              .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
              .alignItems(VerticalAlign.Center)
            }, (gen: EvolutionGenerationSummaryDto) => gen.generationNo.toString() + gen.status)
            Text('写面（审批/参数修改）在 PC 治理页完成，本页只读')
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

          this.groupLabel('shield', '门禁结果摘要（最近一代）')

          // 门禁结果摘要卡：G0-G4 三态徽标逐门呈报 + 裁决与部署结论
          Column() {
            if (this.latestDetail === null) {
              Text(this.errorText.length > 0 ? '无最近一代可读' : (this.loading ? '加载中…' : '暂无门禁读数'))
                .fontSize(12.5)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 6, bottom: 6 })
            } else {
              ForEach(this.verdictKeys(), (key: string) => {
                Row() {
                  Text(key)
                    .fontSize(12.5)
                    .fontColor(this.sm.getColor('text_secondary'))
                    .layoutWeight(1)
                  StatusPill({
                    variant: verdictVariantOf(this.latestDetail!.verdicts[key].state),
                    text: verdictLabelOf(this.latestDetail!.verdicts[key].state),
                  })
                  Text(this.latestDetail!.verdicts[key].reason.length > 0 ? this.latestDetail!.verdicts[key].reason : '')
                    .fontSize(10.5)
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .margin({ left: 8 })
                    .constraintSize({ maxWidth: '50%' })
                    .maxLines(1)
                }
                .width('100%')
                .padding({ top: 8, bottom: 8 })
                .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
                .alignItems(VerticalAlign.Center)
              }, (key: string) => key + this.latestDetail!.verdicts[key].state)
              Text('裁决：' + decisionLabelOf(
                this.latestDetail.decision !== null ? this.latestDetail.decision.kind : '',
                this.latestDetail.decision !== null ? this.latestDetail.decision.approver : '',
                this.latestDetail.decision !== null ? this.latestDetail.decision.reason : ''))
                .fontSize(11.5)
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ top: 8 })
              if (this.latestDetail.deployment !== null && this.latestDetail.deployment.canaryConclusion.length > 0) {
                Text('金丝雀结论：' + this.latestDetail.deployment.canaryConclusion)
                  .fontSize(11.5)
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ top: 3 })
              }
              if (this.latestDetail.deployment !== null && this.latestDetail.deployment.rolledBackTo !== null) {
                Text('已回滚至世代 #' + this.latestDetail.deployment.rolledBackTo.toString())
                  .fontSize(11.5)
                  .fontColor(this.sm.getColor('error'))
                  .margin({ top: 3 })
              }
            }
          }
          .width('calc(100% - 40vp)')
          .padding({ left: 15, right: 15, bottom: 12 })
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
