/**
 * EnterpriseSourcesPage - 企业数据源页（对照原型 F13）
 *
 * 数据：GET /knowledge/enterprise/sources（_view 投影：source_id/descriptor/
 *       enabled/adapter_registered/ingested_count...）。
 * 说明：连接健康探测与源提交是治理动作（服务端仅管理员，403 门控）——
 *       本页先呈现只读列表；探测/提交入口按 role 门控放行（M7 统一接线）。
 * NL2SQL 快问为 env 门控端点（默认关）——留待后端开启后再接，不画假按钮。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { EnterpriseSourceDto } from '../libs/api/modules/KnowledgeEnterpriseApi';

@Component
export struct EnterpriseSourcesPage {
  @State private sources: EnterpriseSourceDto[] = [];
  @State private loading: boolean = false;
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();

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

  private adapterLabel(s: EnterpriseSourceDto): string {
    return s.adapter_registered ? '适配器就绪' : '适配器未注册';
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
        Text('企业数据源')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        Blank()
          .width(38)
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
              Text('源提交是治理动作，请在 PC 端完成（仅管理员）')
                .fontSize(12)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 6 })
            }
            .width('100%')
            .margin({ top: 90 })
          }
          ForEach(this.sources, (s: EnterpriseSourceDto) => {
            Column() {
              Row() {
                Text(s.source_id)
                  .fontSize(13.5)
                  .fontWeight(FontWeight.Medium)
                  .fontColor(this.sm.getColor('text_primary'))
                  .layoutWeight(1)
                Text(this.adapterLabel(s))
                  .fontSize(10)
                  .fontColor(s.adapter_registered ? this.sm.getColor('success') : this.sm.getColor('warning'))
                  .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                  .borderRadius(6)
                  .border({ width: 1, color: s.adapter_registered ? this.sm.getColor('success') : this.sm.getColor('warning') })
              }
              .width('100%')

              Row() {
                Text('已入库 ' + s.ingested_count.toString() + ' 条')
                  .fontSize(11)
                  .fontColor(this.sm.getColor('text_secondary'))
                Text(s.enabled ? '已启用' : '已停用')
                  .fontSize(11)
                  .fontColor(this.sm.getColor('text_tertiary'))
                  .margin({ left: 12 })
                Blank()
                Text('更新于 ' + (s.updated_at.length >= 10 ? s.updated_at.slice(0, 10) : s.updated_at))
                  .fontSize(10.5)
                  .fontColor(this.sm.getColor('text_tertiary'))
              }
              .width('100%')
              .margin({ top: 8 })
            }
            .width('100%')
            .padding(14)
            .borderRadius(16)
            .backgroundColor(this.sm.getColor('surface'))
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ bottom: 10, left: 20, right: 20 })
          }, (s: EnterpriseSourceDto) => s.source_id + s.updated_at)
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
