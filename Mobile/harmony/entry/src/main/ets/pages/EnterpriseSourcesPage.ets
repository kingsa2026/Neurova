/**
 * EnterpriseSourcesPage - 企业数据源页（严格按设计稿 F13 还原）
 *
 * 数据：GET /knowledge/enterprise/sources（_view 投影：source_id/descriptor/
 *       enabled/adapter_registered/ingested_count/updated_at）。
 * 卡片：名称 + 驱动类型徽标（descriptor.driver）+ 状态点（适配器就绪且启用=绿）；
 *       第二行 host:port/database（descriptor 真实连接信息）；第三行 已入库/更新时间/启停。
 * NL2SQL 卡：能力示例展示（真实通道为 env 门控 + 按源端点，默认关——卡内标注示例）。
 * 提交：右上角 + → 表单弹层 → POST /knowledge/enterprise/sources（仅管理员，403 如实透出）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { EnterpriseSourceDto } from '../libs/api/modules/KnowledgeEnterpriseApi';
import { IconBtn } from '../components/common/IconBtn';
import { AppIcon } from '../components/common/AppIcon';
import { GlassInput } from '../components/glass';

/** 驱动选项（connectors_sql 支持域） */
interface DriverOption {
  label: string;
  value: string;
}

@Component
export struct EnterpriseSourcesPage {
  @State private sources: EnterpriseSourceDto[] = [];
  @State private loading: boolean = false;
  // 提交弹层
  @State private submitting: boolean = false;
  @State private busy: boolean = false;
  @State private newId: string = '';
  @State private newDriver: number = 0;
  @State private newHost: string = '';
  @State private newPort: string = '';
  @State private newDatabase: string = '';
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();
  private drivers: DriverOption[] = [
    { label: 'PostgreSQL', value: 'postgresql' },
    { label: 'MySQL', value: 'mysql' },
    { label: 'HTTP API', value: 'http' }
  ];

  aboutToAppear(): void {
    this.loadSources();
  }

  private async loadSources(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.enterprise.listSources();
      if (res.code === 0 && res.data) {
        this.sources = res.data.items;
      } else {
        this.msg.error(res.message || '企业数据源获取失败');
      }
    } catch (e) {
      this.msg.error('企业数据源获取失败：' + (e as Error).message);
    }
    this.loading = false;
  }

  private descStr(s: EnterpriseSourceDto, key: string): string {
    const d = s.descriptor as Record<string, Object>;
    if (!d) {
      return '';
    }
    const v = d[key];
    return v === undefined || v === null ? '' : String(v);
  }

  /** 驱动显示名（driver 值 → 设计徽标文案） */
  private driverLabel(s: EnterpriseSourceDto): string {
    const driver = this.descStr(s, 'driver').toLowerCase();
    if (driver === 'postgresql') {
      return 'PostgreSQL';
    }
    if (driver === 'mysql') {
      return 'MySQL';
    }
    if (driver === 'mssql') {
      return 'SQL Server';
    }
    if (driver === 'oracle') {
      return 'Oracle';
    }
    if (driver === 'http' || this.descStr(s, 'url').length > 0) {
      return 'HTTP API';
    }
    return driver.length > 0 ? driver : '未知';
  }

  /** 连接串行（host:port/database 或 url） */
  private connLine(s: EnterpriseSourceDto): string {
    const url = this.descStr(s, 'url');
    if (url.length > 0) {
      return url;
    }
    const host = this.descStr(s, 'host');
    const port = this.descStr(s, 'port');
    const db = this.descStr(s, 'database');
    return `${host}${port.length > 0 ? ':' + port : ''}${db.length > 0 ? ' / ' + db : ''}`;
  }

  /** 状态点：适配器就绪且启用=绿，否则黄（设计 .dot ok/warn） */
  private dotColor(s: EnterpriseSourceDto): string {
    return s.adapter_registered && s.enabled ? this.sm.getColor('success') : this.sm.getColor('warning');
  }

  private dotLabel(s: EnterpriseSourceDto): string {
    return s.adapter_registered && s.enabled ? '健康' : '需重测';
  }

  private async submitSource(): Promise<void> {
    if (this.newId.trim().length === 0 || this.newHost.trim().length === 0) {
      this.msg.warning('源 ID 与主机不能为空');
      return;
    }
    this.busy = true;
    try {
      const driver = this.drivers[this.newDriver].value;
      const desc: Record<string, Object> = {
        'driver': driver,
        'host': this.newHost.trim(),
        'database': this.newDatabase.trim(),
      };
      if (this.newPort.trim().length > 0) {
        desc['port'] = Number(this.newPort.trim());
      }
      const body: Record<string, Object> = {
        'source_id': this.newId.trim(),
        'descriptor': desc,
      };
      const res = await this.api.enterprise.submitSource(body);
      if (res.code === 0) {
        this.msg.success('数据源已提交');
        this.submitting = false;
        this.loadSources();
      } else {
        this.msg.error(res.message || '提交失败');
      }
    } catch (e) {
      this.msg.error('提交失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  build() {
    Stack() {
      Column() {
        // 头部（设计 .phead：返回 + 企业数据源 + 加号）
        Row() {
          IconBtn({ name: 'back', onTap: () => { this.router.back(); } })
          Text('企业数据源')
            .fontSize(17)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .textAlign(TextAlign.Center)
          IconBtn({ name: 'plus', accent: true, onTap: () => { this.submitting = true; } })
        }
        .width('100%')
        .padding({ left: 12, right: 12, top: 6, bottom: 8 })

        Scroll() {
          Column() {
            if (this.sources.length === 0 && !this.loading) {
              Column() {
                Text('暂无已提交数据源')
                  .fontSize(14)
                  .fontColor(this.sm.getColor('text_tertiary'))
                Text('源提交是治理动作，仅管理员可完成')
                  .fontSize(12)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .margin({ top: 6 })
              }
              .width('100%')
              .margin({ top: 90 })
            }

            // 数据源卡（设计 .src-card：名称+类型徽标+状态点 / 连接串 / 摘要行）
            ForEach(this.sources, (s: EnterpriseSourceDto) => {
              Column() {
                Row() {
                  Text(s.source_id)
                    .fontSize(13.5)
                    .fontWeight(FontWeight.Medium)
                    .fontColor(this.sm.getColor('text_primary'))
                    .layoutWeight(1)
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                  Text(this.driverLabel(s))
                    .fontSize(10)
                    .fontColor(this.sm.getColor('primary'))
                    .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                    .borderRadius(6)
                    .backgroundColor(this.sm.getColor('primary_soft'))
                    .border({ width: 1, color: this.sm.getColor('primary') })
                  Row()
                    .width(7)
                    .height(7)
                    .borderRadius(4)
                    .backgroundColor(this.dotColor(s))
                    .margin({ left: 8 })
                }
                .width('100%')
                .alignItems(VerticalAlign.Center)

                Text(this.connLine(s))
                  .fontSize(11.5)
                  .fontFamily(this.sm.getMonoFont())
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ top: 6 })
                  .maxLines(1)
                  .textOverflow({ overflow: TextOverflow.Ellipsis })

                Row() {
                  Text('已入库 ' + s.ingested_count.toString() + ' 条')
                    .fontSize(10.5)
                    .fontColor(this.sm.getColor('text_tertiary'))
                  Text(this.dotLabel(s))
                    .fontSize(10.5)
                    .fontColor(this.dotColor(s))
                    .margin({ left: 10 })
                  Text(s.updated_at.length >= 10 ? '更新于 ' + s.updated_at.slice(0, 10) : '')
                    .fontSize(10.5)
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .margin({ left: 10 })
                  Blank()
                  Text(s.enabled ? '已启用' : '已停用')
                    .fontSize(10.5)
                    .fontColor(this.sm.getColor('text_tertiary'))
                }
                .width('100%')
                .margin({ top: 7 })
              }
              .width('calc(100% - 40vp)')
              .padding(14)
              .borderRadius(16)
              .backgroundColor(this.sm.getColor('glass'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .margin({ bottom: 10, left: 20, right: 20 })
            }, (s: EnterpriseSourceDto) => s.source_id + s.updated_at)

            // NL2SQL 能力卡（设计 .nl2：标题 + 示例问句 + SQL 预览；真实通道 env 门控按源开放）
            Column() {
              Row() {
                AppIcon({ name: 'spark', iconSize: 14, color: this.sm.getColor('primary') })
                Text('自然语言查数（NL2SQL）')
                  .fontSize(12.5)
                  .fontWeight(FontWeight.Medium)
                  .fontColor(this.sm.getColor('text_primary'))
                  .margin({ left: 7 })
              }
              .alignItems(VerticalAlign.Center)
              Text('「上月各渠道转化率 TOP5 是多少？」')
                .fontSize(12)
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ top: 8 })
              Text("SELECT channel, conversion_rate\nFROM monthly_funnel\nWHERE month = '2026-10'\nORDER BY conversion_rate DESC LIMIT 5;")
                .fontSize(10.5)
                .fontFamily(this.sm.getMonoFont())
                .fontColor(this.sm.getColor('text_secondary'))
                .padding(10)
                .borderRadius(10)
                .backgroundColor(this.sm.getColor('surface'))
                .border({ width: 1, color: this.sm.getColor('border') })
                .margin({ top: 8 })
              Text('示例 · 真实快问通道按数据源与开关开放（PC 端完整可用）')
                .fontSize(9.5)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 6 })
            }
            .width('calc(100% - 40vp)')
            .padding(14)
            .borderRadius(16)
            .backgroundColor(this.sm.getColor('glass'))
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ top: 6, left: 20, right: 20 })
            .alignItems(HorizontalAlign.Start)
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

      // 提交数据源弹层（+ 呼出；仅管理员可成——403 如实透出）
      if (this.submitting) {
        Column() {
          Scroll() {
            Column() {
              Text('接入企业数据源')
                .fontSize(15)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.sm.getColor('text_primary'))
              GlassInput({
                placeholder: '源 ID（如 sales_prod）',
                value: this.newId,
                onChange: (v: string) => { this.newId = v; }
              })
                .margin({ top: 12 })
              Row() {
                ForEach(this.drivers, (d: DriverOption, idx: number) => {
                  Text(d.label)
                    .fontSize(11.5)
                    .fontColor(this.newDriver === idx ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
                    .padding({ left: 10, right: 10, top: 6, bottom: 6 })
                    .borderRadius(9)
                    .backgroundColor(this.newDriver === idx ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
                    .border({ width: 1, color: this.newDriver === idx ? this.sm.getColor('primary') : this.sm.getColor('border') })
                    .margin({ right: 6 })
                    .onClick(() => { this.newDriver = idx; })
                }, (d: DriverOption) => d.value)
              }
              .margin({ top: 10 })
              GlassInput({
                placeholder: '主机（如 10.0.12.34）',
                value: this.newHost,
                onChange: (v: string) => { this.newHost = v; }
              })
                .margin({ top: 10 })
              GlassInput({
                placeholder: '端口（可空）',
                value: this.newPort,
                onChange: (v: string) => { this.newPort = v; }
              })
                .margin({ top: 10 })
              GlassInput({
                placeholder: '数据库（可空）',
                value: this.newDatabase,
                onChange: (v: string) => { this.newDatabase = v; }
              })
                .margin({ top: 10 })
              Row() {
                Text('取消')
                  .fontSize(13)
                  .fontColor(this.sm.getColor('text_secondary'))
                  .padding({ left: 14, right: 14, top: 8, bottom: 8 })
                  .onClick(() => { this.submitting = false; })
                Text(this.busy ? '提交中…' : '提交')
                  .fontSize(13)
                  .fontWeight(FontWeight.Medium)
                  .fontColor(this.sm.getColor('text_on_primary'))
                  .padding({ left: 16, right: 16, top: 8, bottom: 8 })
                  .borderRadius(10)
                  .linearGradient({ angle: 135, colors: this.sm.getBrandGradient() })
                  .margin({ left: 8 })
                  .onClick(() => { this.submitSource(); })
              }
              .width('100%')
              .justifyContent(FlexAlign.End)
              .margin({ top: 14 })
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
          }
          .width('82%')
          .padding(16)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface_strong'))
          .border({ width: 1, color: this.sm.getColor('border') })
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
