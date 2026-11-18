/**
 * ModelPage - 模型管理页（对照原型 F11：服务商 + 模型 ID + 能力测试）
 *
 * 数据（provider.py / model.py 源码核对，均为裸数组或 code/data 信封）：
 *   GET  /providers                服务商列表（裸数组 ProviderInfo）
 *   GET  /models                   模型清单（裸数组 ModelInfo，含 capabilities）
 *   GET  /providers/active-model   当前激活模型
 *   POST /providers/activate-model 激活（provider_id + model_id）
 *   POST /providers/{id}/check-connection  连通性测试
 *   POST /providers                创建服务商（name/provider_type/base_url/api_key）
 * 旧 ModelsApi 的 /models/providers*、/models/default、/models/params 系
 * 后端不存在的端点形态，随本次重写退役（ModelsApi 整模块退役，教义第 7 条）。
 */

import { ProvidersApi, ProviderInfoDto, ModelInfoDto, ProviderCreateRequest, ActiveModelDto } from '../libs/api/modules/ProvidersApi';
import { HttpClient } from '../libs/api/HttpClient';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { Router } from '../routing/Router';

@Component
export struct ModelPage {
  @State private providers: ProviderInfoDto[] = [];
  @State private models: ModelInfoDto[] = [];
  @State private activeModel: ActiveModelDto | null = null;
  @State private loading: boolean = false;
  /** 添加服务商浮层 */
  @State private showAdd: boolean = false;
  @State private newName: string = '';
  @State private newType: string = 'openai';
  @State private newBaseUrl: string = '';
  @State private newApiKey: string = '';
  @State private busy: boolean = false;
  private providersApi: ProvidersApi = new ProvidersApi(HttpClient.getInstance());
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();
  private router = Router.getInstance();

  aboutToAppear(): void {
    this.loadAll();
  }

  private async loadAll(): Promise<void> {
    this.loading = true;
    try {
      this.providers = await this.providersApi.list();
      this.models = await this.providersApi.listModels();
      const res = await this.providersApi.activeModel();
      if (res.code === 0 && res.data) {
        this.activeModel = res.data;
      }
    } catch (e) {
      this.msg.error('模型配置加载失败：' + (e as Error).message);
    }
    this.loading = false;
  }

  private async testConnection(p: ProviderInfoDto): Promise<void> {
    this.busy = true;
    try {
      const res = await this.providersApi.checkConnection(p.provider_id);
      if (res.code === 0 && res.data) {
        if (res.data.connected) {
          this.msg.success(p.name + ' 连接成功');
        } else {
          this.msg.error(p.name + ' 连接失败' + (res.data.message.length > 0 ? '：' + res.data.message : ''));
        }
      } else {
        this.msg.error(res.message || '连接测试失败');
      }
    } catch (e) {
      this.msg.error('连接测试失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  private async activate(m: ModelInfoDto): Promise<void> {
    this.busy = true;
    try {
      const res = await this.providersApi.activate(m.provider, m.model_id);
      if (res.code === 0) {
        this.msg.success('已激活 ' + m.name);
        const res2 = await this.providersApi.activeModel();
        if (res2.code === 0 && res2.data) {
          this.activeModel = res2.data;
        }
        this.models = await this.providersApi.listModels();
      } else {
        this.msg.error(res.message || '激活失败');
      }
    } catch (e) {
      this.msg.error('激活失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  private async submitAdd(): Promise<void> {
    if (this.newName.trim().length === 0 || this.newApiKey.trim().length === 0) {
      this.msg.warning('名称与 API Key 不能为空');
      return;
    }
    this.busy = true;
    try {
      const data: ProviderCreateRequest = {
        name: this.newName.trim(),
        provider_type: this.newType,
        base_url: this.newBaseUrl.trim(),
        api_key: this.newApiKey.trim(),
      };
      const res = await this.providersApi.create(data);
      if (res.code === 0 && res.data) {
        this.msg.success('服务商已创建');
        this.showAdd = false;
        this.newName = '';
        this.newBaseUrl = '';
        this.newApiKey = '';
        // 创建即测连通性（原型 F11 交互）
        await this.testConnection(res.data);
        this.providers = await this.providersApi.list();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.msg.error('创建失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  /** 该服务商下的模型 */
  private modelsOf(providerId: string): ModelInfoDto[] {
    return this.models.filter((m: ModelInfoDto) => m.provider === providerId);
  }

  build() {
    Stack() {
      Column() {
        // 头部
        Row() {
          Text('模型管理')
            .fontSize(21)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
          Blank()
          Button() {
            Text('＋ 服务商')
              .fontSize(13)
              .fontColor(this.sm.getColor('text_on_primary'))
          }
          .height(34)
          .backgroundColor(this.sm.getColor('primary'))
          .onClick(() => {
            this.showAdd = true;
          })
        }
        .width('100%')
        .padding({ left: 20, right: 20, top: 8, bottom: 10 })

        // 当前激活模型
        Row() {
          Text('当前默认')
            .fontSize(12)
            .fontColor(this.sm.getColor('text_tertiary'))
          Text(this.activeModel && this.activeModel.model
            ? this.activeModel.model + (this.activeModel.provider ? ' · ' + this.activeModel.provider : '')
            : '未设置（在下方模型点「设为默认」）')
            .fontSize(12.5)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ left: 10 })
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('calc(100% - 40vp)')
        .margin({ left: 20, right: 20, bottom: 12 })
        .padding(12)
        .borderRadius(12)
        .backgroundColor(this.sm.getColor('primary_soft'))

        Scroll() {
          Column() {
            ForEach(this.providers, (p: ProviderInfoDto) => {
              Column() {
                Row() {
                  Text(p.name)
                    .fontSize(14.5)
                    .fontWeight(FontWeight.Medium)
                    .fontColor(this.sm.getColor('text_primary'))
                  Text(p.provider_type)
                    .fontSize(9)
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                    .borderRadius(6)
                    .border({ width: 1, color: this.sm.getColor('border') })
                    .margin({ left: 8 })
                  Blank()
                  Text('测试连接')
                    .fontSize(11)
                    .fontColor(this.sm.getColor('primary'))
                    .padding(6)
                    .onClick(() => {
                      this.testConnection(p);
                    })
                }
                .width('100%')

                if (p.base_url.length > 0) {
                  Text(p.base_url)
                    .fontSize(10)
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .margin({ top: 3 })
                    .maxLines(1)
                }

                ForEach(this.modelsOf(p.provider_id), (m: ModelInfoDto) => {
                  Row() {
                    Column() {
                      Row() {
                        Text(m.name)
                          .fontSize(13)
                          .fontWeight(FontWeight.Medium)
                          .fontColor(this.sm.getColor('text_primary'))
                        Text(m.model_id)
                          .fontSize(9.5)
                          .fontFamily(this.sm.getMonoFont())
                          .fontColor(this.sm.getColor('text_tertiary'))
                          .margin({ left: 6 })
                        if (m.is_active || (this.activeModel && this.activeModel.model === m.model_id)) {
                          Text('默认')
                            .fontSize(9)
                            .fontColor(this.sm.getColor('text_on_primary'))
                            .backgroundColor(this.sm.getColor('primary'))
                            .padding({ left: 5, right: 5, top: 1, bottom: 1 })
                            .borderRadius(5)
                        }
                      }
                      // 能力胶囊（设计 F11 .cap：对话/视觉/工具调用/长文本）
                      Row() {
                        ForEach(m.capabilities, (c: string) => {
                          Text(c)
                            .fontSize(9)
                            .fontColor(this.sm.getColor('primary'))
                            .backgroundColor(this.sm.getColor('primary_soft'))
                            .border({ width: 1, color: this.sm.getColor('primary') })
                            .borderRadius(5)
                            .padding({ left: 7, right: 7, top: 2, bottom: 2 })
                            .margin({ right: 5, bottom: 3 })
                        }, (c: string) => c)
                        if (m.capabilities.length === 0) {
                          Text('未探测')
                            .fontSize(10)
                            .fontColor(this.sm.getColor('text_tertiary'))
                        }
                      }
                      .margin({ top: 4 })
                    }
                    .alignItems(HorizontalAlign.Start)
                    .layoutWeight(1)

                    Text('设为默认')
                      .fontSize(11)
                      .fontColor(this.sm.getColor('primary'))
                      .padding(6)
                      .onClick(() => {
                        this.activate(m);
                      })
                  }
                  .width('100%')
                  .padding({ top: 10, bottom: 4 })
                  .border({ width: { top: 1 }, color: this.sm.getColor('divider') })
                }, (m: ModelInfoDto) => m.model_id)
              }
              .width('calc(100% - 40vp)')
              .padding(14)
              .borderRadius(16)
              .backgroundColor(this.sm.getColor('glass'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .margin({ bottom: 10, left: 20, right: 20 })
            }, (p: ProviderInfoDto) => p.provider_id)
          }
          .width('100%')
        }
        .layoutWeight(1)
        .scrollBar(BarState.Off)
        .width('100%')
      }
      .width('100%')
      .height('100%')

      // 添加服务商浮层
      if (this.showAdd) {
        Column() {
          Column() {
            Text('添加服务商')
              .fontSize(16)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ bottom: 12 })
            TextInput({ placeholder: '服务商名称（如 OpenAI 官方）' })
              .onChange((v: string) => {
                this.newName = v;
              })
              .height(42)
              .borderRadius(12)
              .backgroundColor(this.sm.getColor('surface_strong'))
            TextInput({ text: this.newBaseUrl, placeholder: 'Base URL（https://api.openai.com/v1）' })
              .onChange((v: string) => {
                this.newBaseUrl = v;
              })
              .height(42)
              .borderRadius(12)
              .backgroundColor(this.sm.getColor('surface_strong'))
              .margin({ top: 9 })
            TextInput({ text: this.newApiKey, placeholder: 'API Key' })
              .onChange((v: string) => {
                this.newApiKey = v;
              })
              .height(42)
              .borderRadius(12)
              .backgroundColor(this.sm.getColor('surface_strong'))
              .margin({ top: 9 })
            Row() {
              ForEach(['openai', 'anthropic', 'ollama', 'gemini'], (t: string) => {
                Text(t)
                  .fontSize(11)
                  .fontColor(this.newType === t ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
                  .padding({ left: 10, right: 10, top: 4, bottom: 4 })
                  .borderRadius(999)
                  .backgroundColor(this.newType === t ? this.sm.getColor('primary_soft') : this.sm.getColor('surface'))
                  .border({ width: 1, color: this.newType === t ? this.sm.getColor('primary') : this.sm.getColor('border') })
                  .margin({ right: 6 })
                  .onClick(() => {
                    this.newType = t;
                  })
              }, (t: string) => t)
              Blank()
            }
            .width('100%')
            .margin({ top: 4 })

            Row() {
              Button('取消')
                .layoutWeight(1)
                .height(40)
                .backgroundColor(this.sm.getColor('surface_strong'))
                .fontColor(this.sm.getColor('text_secondary'))
                .onClick(() => {
                  this.showAdd = false;
                })
              Button('保存并测试')
                .layoutWeight(1)
                .height(40)
                .backgroundColor(this.sm.getColor('primary'))
                .fontColor(this.sm.getColor('text_on_primary'))
                .margin({ left: 10 })
                .enabled(!this.busy)
                .onClick(() => {
                  this.submitAdd();
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
          this.showAdd = false;
        })
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
