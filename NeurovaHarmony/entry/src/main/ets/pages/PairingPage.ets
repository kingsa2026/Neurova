/**
 * PairingPage - 移动端配对页
 *
 * 职责：完成移动端与 Neurova 后端的配对闭环，获取 WebSocket 连接凭证
 * 设计：Stack 叠加 [星空背景] + Column [TopNavMenu] + Scroll [设备信息卡片 + Tab 切换 + 配对区]；
 *       支持两种配对方式：
 *         1. 扫码配对：调用 PlatformAdapter.scanQRCode() 识别 neurova://pair?code=XXXXXX
 *         2. 输入配对码：6 格分隔式数字输入框，自动跳格
 *       配对流程：获取 code → api.mobilePairing.confirm → 写入 wsToken/wsUrl 到 AuthStore → 跳转 Dashboard
 *       状态机：idle → waiting → success（1.5s 后跳转）/ failed（展示错误 + 重试）
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、StarBackground
 *   - ../libs/api/ApiFacade：mobilePairing.confirm
 *   - ../libs/state/stores/AuthStore：写入配对后的 wsToken/wsUrl
 *   - ../libs/adapters/PlatformAdapter：scanQRCode / getDeviceInfo
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：PairingConfirm
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *
 * 用法：
 *   由 Router.push(RouteNames.PAIRING) 跳转进入；
 *   配对成功后 replace 到 DashboardPage
 */

import { TopNavMenu, GlassCard, GlassButton, StarBackground } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { PlatformAdapter, DeviceInfo } from '../libs/adapters/PlatformAdapter';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { PairingConfirm } from '../libs/types';

/** 配对方式：scan=扫码，input=手动输入 */
type PairingMode = 'scan' | 'input';

/** 配对状态机：idle=待操作，waiting=配对中，success=成功，failed=失败 */
type PairingStatus = 'idle' | 'waiting' | 'success' | 'failed';

/** 日志标签 */
const TAG = 'PairingPage';

/** 配对码长度（固定 6 位） */
const CODE_LENGTH = 6;

/** 配对码在二维码中的正则（QR 内容格式：neurova://pair?code=XXXXXX） */
const QR_CODE_PATTERN = /code=([A-Za-z0-9]{6})/;

/** 配对成功后跳转 Dashboard 的延迟（毫秒），用于展示"配对成功"反馈 */
const SUCCESS_REDIRECT_DELAY = 1500;

@Component
export struct PairingPage {
  // 当前配对方式（默认扫码）
  @State mode: PairingMode = 'scan';
  // 当前配对状态
  @State status: PairingStatus = 'idle';
  // 6 位配对码（与 cells 同步，作为 confirm 入参的权威来源）
  @State code: string = '';
  // 6 格输入框各格内容（输入模式专用）
  @State cells: string[] = ['', '', '', '', '', ''];
  // 当前设备名（confirm 入参）
  @State deviceName: string = 'HarmonyOS-Device';
  // 错误信息（status===failed 时展示）
  @State errorMessage: string = '';
  // 设备信息（用于展示品牌/型号/系统版本）
  @State deviceInfo: DeviceInfo = {
    brand: 'unknown', model: 'unknown', osVersion: 'unknown',
    osName: 'harmony', apiVersion: 0, screenW: 0, screenH: 0,
  };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private authStore = new AuthStore();
  private platform = PlatformAdapter.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    // 拉取设备信息并拼装设备名：brand-model（如 HUAWEI-ABC001）
    try {
      const info = this.platform.getDeviceInfo();
      this.deviceInfo = info;
      this.deviceName = `${info.brand}-${info.model}`;
    } catch (e) {
      // getDeviceInfo 内部已有兜底，此处仅记录，不阻塞页面
      this.logger.warn(TAG, '获取设备信息失败，使用默认设备名', e as Error);
    }
  }

  /**
   * 扫码配对
   * 流程：调起系统扫码 → 从 QR 内容解析 6 位 code → 触发 confirmPairing
   * 异常：用户取消、无效二维码、扫码失败均置 failed 并展示原因
   */
  private async handleScan(): Promise<void> {
    this.status = 'waiting';
    this.errorMessage = '';
    try {
      const scanned = await this.platform.scanQRCode();
      // 解析 QR 内容中的配对码（格式：neurova://pair?code=XXXXXX）
      const match = scanned.match(QR_CODE_PATTERN);
      if (!match) {
        this.status = 'failed';
        this.errorMessage = '无效的配对二维码';
        this.logger.warn(TAG, `扫码内容未匹配到配对码: ${scanned.slice(0, 100)}`);
        return;
      }
      this.code = match[1];
      this.syncCodeToCells(this.code);
      await this.confirmPairing();
    } catch (e) {
      this.status = 'failed';
      this.errorMessage = (e as Error).message;
      this.logger.error(TAG, '扫码失败', e as Error);
    }
  }

  /**
   * 确认配对（核心闭环）
   * 流程：校验 6 位 code → 调用 mobilePairing.confirm → 写入 wsToken/wsUrl → 置 success → 延迟跳转
   * 异常：业务失败展示后端 message；网络/未知异常展示错误信息并记录日志
   */
  private async confirmPairing(): Promise<void> {
    if (this.code.length !== CODE_LENGTH) {
      this.msg.warning(`请输入 ${CODE_LENGTH} 位配对码`);
      return;
    }
    this.status = 'waiting';
    this.errorMessage = '';
    try {
      const form: PairingConfirm = {
        code: this.code,
        deviceName: this.deviceName,
        deviceType: 'harmony',
      };
      const res = await this.api.mobilePairing.confirm(form);
      if (res.code === 0 && res.data) {
        // 写入 WebSocket 凭证到 AuthStore，供后续 WS 连接使用
        this.authStore.setWsPairing(res.data.wsToken, res.data.wsUrl);
        this.status = 'success';
        this.msg.success('配对成功');
        // 延迟跳转，让用户看到"配对成功"反馈
        setTimeout(() => {
          this.router.replace(RouteNames.DASHBOARD);
        }, SUCCESS_REDIRECT_DELAY);
      } else {
        this.status = 'failed';
        this.errorMessage = res.message || '配对失败';
      }
    } catch (e) {
      this.status = 'failed';
      this.errorMessage = (e as Error).message;
      this.logger.error(TAG, '配对失败', e as Error);
    }
  }

  /**
   * 输入模式：单格内容变化处理
   * - 取输入末位字符作为本格内容（避免 maxLength 截断外的残留）
   * - 输入有效字符后自动 focus 下一格；末格输入完成不自动提交，由"确认配对"按钮触发
   * - 清空本格时停留（用户可点击上一格继续修改）
   * @param index 当前格索引 0-5
   * @param value 当前格 TextInput 回传值
   */
  private onCellChange(index: number, value: string): void {
    // 取末位字符（TextInput 即便 maxLength=1 也可能传入多字符粘贴场景）
    const ch = value.length > 0 ? value.charAt(value.length - 1) : '';
    // 重新生成数组以触发 @State 更新（ArkUI 对数组元素直接赋值不会触发渲染）
    const next = this.cells.slice();
    next[index] = ch;
    this.cells = next;
    this.code = this.cells.join('');

    // 输入了字符且非末格：自动 focus 下一格
    if (ch.length === 1 && index < CODE_LENGTH - 1) {
      try {
        focusControl.requestFocus(`pairing_cell_${index + 1}`);
      } catch (e) {
        // focus 失败不阻塞流程，仅记录
        this.logger.warn(TAG, `focus 下一格失败: index=${index + 1}`, e as Error);
      }
    }
  }

  /** 将完整 code 同步到 6 格（扫码后回填输入格用） */
  private syncCodeToCells(code: string): void {
    const arr: string[] = [];
    for (let i = 0; i < CODE_LENGTH; i++) {
      arr.push(i < code.length ? code.charAt(i) : '');
    }
    this.cells = arr;
  }

  /** 重置为初始状态，供"重试"按钮调用 */
  private resetToIdle(): void {
    this.status = 'idle';
    this.errorMessage = '';
    this.code = '';
    this.cells = ['', '', '', '', '', ''];
  }

  /**
   * 输入模式失败重试：回到 idle 但保留已输入的 code，便于用户修正后重新提交
   * 与 resetToIdle 的区别：不清空 code/cells
   */
  private retryInput(): void {
    this.status = 'idle';
    this.errorMessage = '';
  }

  build() {
    Stack() {
      // 背景层：星空
      StarBackground({ starCount: 60, twinkle: true })

      // 内容层
      Column() {
        // 顶部导航：标题"配对" + 返回
        TopNavMenu({
          title: '配对',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 滚动内容区
        Scroll() {
          Column() {
            // 1. 当前设备信息卡片
            GlassCard({ title: '当前设备' }) {
              Column() {
                Text(`${this.deviceInfo.brand} ${this.deviceInfo.model}`)
                  .fontSize(this.sm.getFontSize('body'))
                  .fontColor(this.sm.getColor('text_primary'))

                Text(`系统：HarmonyOS ${this.deviceInfo.osVersion}`)
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ top: 4 })
              }
              .width('100%')
              .alignItems(HorizontalAlign.Start)
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // 2. Tab 切换：扫码配对 / 输入配对码
            Row() {
              Text('扫码配对')
                .fontSize(this.sm.getFontSize('body'))
                .fontColor(this.mode === 'scan'
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('text_secondary'))
                .fontWeight(this.mode === 'scan' ? FontWeight.Bold : FontWeight.Normal)
                .layoutWeight(1)
                .textAlign(TextAlign.Center)
                .padding({ top: 8, bottom: 8 })
                .onClick(() => { this.mode = 'scan'; this.resetToIdle(); })

              Text('输入配对码')
                .fontSize(this.sm.getFontSize('body'))
                .fontColor(this.mode === 'input'
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('text_secondary'))
                .fontWeight(this.mode === 'input' ? FontWeight.Bold : FontWeight.Normal)
                .layoutWeight(1)
                .textAlign(TextAlign.Center)
                .padding({ top: 8, bottom: 8 })
                .onClick(() => { this.mode = 'input'; this.resetToIdle(); })
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })
            .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })

            // 3. 配对区：按 mode 与 status 渲染
            if (this.mode === 'scan') {
              this.buildScanArea()
            } else {
              this.buildInputArea()
            }
          }
          .width('100%')
          .padding(this.sm.getSpacing('md'))
          .alignItems(HorizontalAlign.Start)
        }
        .layoutWeight(1)
        .width('100%')
        .scrollBar(BarState.Off)
        .align(Alignment.TopStart)
      }
      .width('100%')
      .height('100%')
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 扫码配对区构建器
  // ===========================================================================
  @Builder
  buildScanArea() {
    GlassCard({ title: '扫码配对' }) {
      Column() {
        if (this.status === 'idle') {
          // 待操作：大按钮触发扫码
          Text('使用系统扫码识别 Neurova 配对二维码')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .textAlign(TextAlign.Center)
            .margin({ bottom: this.sm.getSpacing('md') })

          GlassButton({
            text: '扫码配对',
            type: 'primary',
            block: true,
            size: 'large',
            onClick: () => { this.handleScan(); }
          })
        } else if (this.status === 'waiting') {
          // 配对中：旋转动画 + 文案，回显识别到的配对码
          LoadingProgress()
            .width(48)
            .height(48)
            .color(this.sm.getColor('primary'))

          Text('等待配对...')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })

          if (this.code.length === CODE_LENGTH) {
            Text(`配对码：${this.code}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .margin({ top: this.sm.getSpacing('xs') })
          }
        } else if (this.status === 'success') {
          // 成功：勾选 + 文案
          Text('✓')
            .fontSize(40)
            .fontColor(this.sm.getColor('success'))
          Text('配对成功')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('success'))
            .margin({ top: this.sm.getSpacing('sm') })
          Text('即将跳转仪表盘...')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('xs') })
        } else {
          // 失败：错误信息 + 重试
          Text('✗')
            .fontSize(40)
            .fontColor(this.sm.getColor('error'))
          Text('配对失败')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('error'))
            .margin({ top: this.sm.getSpacing('sm') })
          if (this.errorMessage) {
            Text(this.errorMessage)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .textAlign(TextAlign.Center)
              .margin({ top: this.sm.getSpacing('xs'), bottom: this.sm.getSpacing('md') })
          }
          GlassButton({
            text: '重试',
            type: 'primary',
            block: true,
            onClick: () => { this.resetToIdle(); }
          })
            .margin({ top: this.sm.getSpacing('sm') })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Center)
    }
    .width('100%')
  }

  // ===========================================================================
  // 输入配对码区构建器
  // ===========================================================================
  @Builder
  buildInputArea() {
    GlassCard({ title: '输入配对码' }) {
      Column() {
        if (this.status === 'success') {
          // 成功态：与扫码成功一致
          Text('✓')
            .fontSize(40)
            .fontColor(this.sm.getColor('success'))
          Text('配对成功')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('success'))
            .margin({ top: this.sm.getSpacing('sm') })
          Text('即将跳转仪表盘...')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('xs') })
        } else {
          // 6 格分隔式输入框
          Row() {
            ForEach([0, 1, 2, 3, 4, 5], (i: number) => {
              TextInput({ text: this.cells[i], placeholder: '' })
                .type(InputType.Normal)
                .maxLength(1)
                .fontSize(22)
                .textAlign(TextAlign.Center)
                .width(40)
                .height(50)
                .margin({ left: i === 0 ? 0 : 4, right: 4 })
                .borderRadius(this.sm.getRadius('sm'))
                .border({
                  width: 1,
                  color: this.sm.getColor('border')
                })
                .backgroundColor(Color.Transparent)
                .fontColor(this.sm.getColor('text_primary'))
                .key(`pairing_cell_${i}`)
                .enabled(this.status !== 'waiting')
                .onChange((v: string) => { this.onCellChange(i, v); })
            }, (i: number) => `cell_${i}`)
          }
          .width('100%')
          .justifyContent(FlexAlign.Center)
          .margin({ top: this.sm.getSpacing('sm'), bottom: this.sm.getSpacing('md') })

          if (this.status === 'waiting') {
            // 配对中：旋转动画 + 文案
            LoadingProgress()
              .width(36)
              .height(36)
              .color(this.sm.getColor('primary'))
            Text('配对中...')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: this.sm.getSpacing('xs'), bottom: this.sm.getSpacing('sm') })
          } else if (this.status === 'failed') {
            // 失败：错误信息 + 重试（保留已输入 code，便于修正后重新提交）
            if (this.errorMessage) {
              Text(this.errorMessage)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('error'))
                .textAlign(TextAlign.Center)
                .margin({ bottom: this.sm.getSpacing('sm') })
            }
            GlassButton({
              text: '重试',
              type: 'primary',
              block: true,
              onClick: () => { this.retryInput(); }
            })
          } else {
            // 待操作：确认配对按钮（code 不足 6 位时禁用）
            GlassButton({
              text: '确认配对',
              type: 'primary',
              block: true,
              disabled: this.code.length !== CODE_LENGTH,
              onClick: () => { this.confirmPairing(); }
            })
          }

          // 通用错误信息兜底（非 failed 状态下若有残留错误也展示）
          if (this.errorMessage && this.status !== 'failed') {
            Text(this.errorMessage)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('error'))
              .margin({ top: this.sm.getSpacing('xs') })
          }
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Center)
    }
    .width('100%')
  }
}
