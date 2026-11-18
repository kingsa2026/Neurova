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
import { AppIcon } from '../components/common/AppIcon';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { PlatformAdapter, DeviceInfo } from '../libs/adapters/PlatformAdapter';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { PairingConfirm, PairingResolved } from '../libs/types';
import { PairingPayload, ParsedPairingPayload } from '../libs/protocol/PairingPayload';
import { ServerProfiles, ServerProfile } from '../libs/config/ServerProfiles';
import { ConfigManager } from '../libs/config/ConfigManager';

/** 配对方式：scan=扫码，input=手动输入 */
type PairingMode = 'scan' | 'input';

/** 配对状态机：idle=待操作，resolving=已扫码换地址中，waiting=配对中，success=成功，failed=失败 */
type PairingStatus = 'idle' | 'resolving' | 'waiting' | 'success' | 'failed';

/** 日志标签 */
const TAG = 'PairingPage';

/** 配对码长度（固定 6 位） */
const CODE_LENGTH = 6;

/** 配对成功后跳转 Dashboard 的延迟（毫秒），用于展示"配对成功"反馈 */
const SUCCESS_REDIRECT_DELAY = 1500;

/** 仅含业务码的最小响应形状（resFailed 判定用；ApiResponse 等结构天然兼容） */
interface CodeOnlyResponse {
  code: number;
}

/** ApiResponse 业务失败判定（code!==0） */
function resFailed(res: CodeOnlyResponse): boolean {
  return res.code !== 0;
}

@Component
export struct PairingPage {
  // 当前配对方式（默认扫码）
  @State mode: PairingMode = 'scan';
  // 扫码解析出的一次性 ref（新流程）或 6 位码（旧兼容）
  @State pairingRef: string = '';
  // 当前配对状态
  @State status: PairingStatus = 'idle';
  // 6 位配对码（与 cells 同步，作为 confirm 入参的权威来源）
  @State code: string = '';
  // 6 格输入框各格内容（输入模式专用）
  @State cells: string[] = ['', '', '', '', '', ''];
  // 当前聚焦的输入格（-1=无），用于聚焦高亮边框
  @State focusedCell: number = -1;
  // 当前设备名（confirm 入参）
  @State deviceName: string = 'HarmonyOS-Device';
  // 错误信息（status===failed 时展示）
  @State errorMessage: string = '';
  // 设备信息（用于展示品牌/型号/系统版本）
  @State deviceInfo: DeviceInfo = {
    brand: 'unknown', model: 'unknown', osVersion: 'unknown',
    osName: 'harmony', apiVersion: 0, screenW: 0, screenH: 0,
  };
  // 取景框扫描线相位（F2 .scanline：上下往复）
  @State scanPhase: boolean = false;
  // 扫描线动画定时器句柄
  private scanTimer: number = -1;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private authStore = new AuthStore();
  private platform = PlatformAdapter.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  async aboutToAppear() {
    // 拉取设备信息并拼装设备名：brand-model（如 HUAWEI-ABC001）
    try {
      const info = this.platform.getDeviceInfo();
      this.deviceInfo = info;
      this.deviceName = `${info.brand}-${info.model}`;
    } catch (e) {
      // getDeviceInfo 内部已有兜底，此处仅记录，不阻塞页面
      this.logger.warn(TAG, '获取设备信息失败，使用默认设备名', e as Error);
    }
    // 扫描线往复动画（2.6s 一循环，与原型 @keyframes scan 同周期）
    this.scanTimer = setInterval(() => {
      this.scanPhase = !this.scanPhase;
    }, 1300);
    // C7：配对深链直达（neurova://pair?ref=…&host=…，与扫码同一载荷解析）
    try {
      const params = this.router.getCurrentParam() as Record<string, Object> | undefined;
      const deepLinkUri = params ? String(params['deepLinkUri'] ?? '') : '';
      if (deepLinkUri) {
        this.logger.info(TAG, '消费配对深链');
        const parsed = PairingPayload.parse(deepLinkUri);
        if (parsed) {
          await this.applyPairingPayload(parsed);
        } else {
          this.status = 'failed';
          this.errorMessage = '配对链接无效';
          this.logger.warn(TAG, `深链未匹配到配对载荷: ${deepLinkUri.slice(0, 100)}`);
        }
      }
    } catch (e) {
      this.status = 'failed';
      this.errorMessage = (e as Error).message;
      this.logger.error(TAG, '配对深链消费失败', e as Error);
    }
  }

  aboutToDisappear() {
    if (this.scanTimer !== -1) {
      clearInterval(this.scanTimer);
      this.scanTimer = -1;
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
      // 载荷解析单源：ref=新流程（凭据与地址分离），code=旧兼容
      const parsed = PairingPayload.parse(scanned);
      if (!parsed) {
        this.status = 'failed';
        this.errorMessage = '无效的配对二维码';
        this.logger.warn(TAG, `扫码内容未匹配到配对载荷: ${scanned.slice(0, 100)}`);
        return;
      }
      await this.applyPairingPayload(parsed);
    } catch (e) {
      this.status = 'failed';
      this.errorMessage = (e as Error).message;
      this.logger.error(TAG, '扫码失败', e as Error);
    }
  }

  /** 配对载荷统一入口（扫码与深链共用，C7 收口）：ref=新流程，code=旧兼容 */
  private async applyPairingPayload(parsed: ParsedPairingPayload): Promise<void> {
    if (parsed.kind === 'ref') {
      // 一扫配全：载荷带对外地址时，先确保服务器档案存在并激活（扫码即完成连接配置）
      if (parsed.host) {
        await this.ensureServerProfile(parsed.host);
      }
      // 新流程：ref → resolve 换回连地址 → confirm（带 ref）
      this.pairingRef = parsed.value;
      await this.resolveAndConfirm();
      return;
    }
    // 旧兼容：6 位码直连 confirm
    this.code = parsed.value;
    this.syncCodeToCells(this.code);
    await this.confirmPairing();
  }

  /** 一扫配全：按二维码里的对外地址确保服务器档案存在并激活（已存在则复用） */
  private async ensureServerProfile(host: string): Promise<void> {
    const store = ServerProfiles.getInstance();
    const existing = store.getList().find((p: ServerProfile) => p.baseUrl === host);
    const target = existing ?? await store.add('扫码配对', host);
    await store.switchTo(target.id);
    await ConfigManager.getInstance().applyServerProfile(`${target.baseUrl}/api/v1`, getContext(this) as Context);
    this.logger.info(TAG, `服务器档案就绪：${target.baseUrl}`);
  }

  /**
   * 新流程：resolve（ref 一次性消费，换回连地址）→ confirm（带 ref）
   * 对应设计方案 §3.4；resolve 失败分型给文案（过期/已用/网络）。
   */
  private async resolveAndConfirm(): Promise<void> {
    this.status = 'resolving';
    this.errorMessage = '';
    try {
      const resolved = await this.api.mobilePairing.resolve(this.pairingRef);
      if (resFailed(resolved)) {
        this.status = 'failed';
        this.errorMessage = resolved.message || '换取连接地址失败';
        return;
      }
      const info: PairingResolved = resolved.data as PairingResolved;
      this.logger.info(TAG, `resolve 成功，回连地址已换取（pairingId=${info.pairingId}）`);
      await this.confirmPairing();
    } catch (e) {
      this.status = 'failed';
      this.errorMessage = (e as Error).message;
      this.logger.error(TAG, 'resolve 失败', e as Error);
    }
  }

  /**
   * 确认配对（核心闭环）
   * 流程：校验 6 位 code → 调用 mobilePairing.confirm → 写入 wsToken/wsUrl → 置 success → 延迟跳转
   * 异常：业务失败展示后端 message；网络/未知异常展示错误信息并记录日志
   */
  private async confirmPairing(): Promise<void> {
    const usingRef = this.pairingRef.length > 0;
    if (!usingRef && this.code.length !== CODE_LENGTH) {
      this.msg.warning(`请输入 ${CODE_LENGTH} 位配对码`);
      return;
    }
    this.status = 'waiting';
    this.errorMessage = '';
    try {
      const form: PairingConfirm = usingRef
        ? { ref: this.pairingRef, deviceName: this.deviceName, deviceType: 'harmony' }
        : { code: this.code, deviceName: this.deviceName, deviceType: 'harmony' };
      const res = await this.api.mobilePairing.confirm(form);
      if (res.code === 0 && res.data) {
        // 写入 WebSocket 凭证到 AuthStore，供后续 WS 连接使用
        this.authStore.setWsPairing(res.data.wsToken, res.data.wsUrl);
        // 长期设备身份入库：refresh 续签免回屏重扫（设计方案 §4.7）
        if (res.data.pairingId && res.data.deviceSecret) {
          this.authStore.setDeviceIdentity(res.data.pairingId, res.data.deviceSecret);
        }
        this.status = 'success';
        this.msg.success('配对成功');
        // 延迟跳转，让用户看到"配对成功"反馈
        setTimeout(() => {
          // 已登录（换服务器重配对）回仪表盘；首次配对先去登录
          if (this.authStore.isAuthenticated) {
            this.router.replace(RouteNames.SHELL);
          } else {
            this.router.replace(RouteNames.LOGIN);
          }
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
    this.pairingRef = '';
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
            Column() {
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
    Column() {
      GlassCard({ title: '扫码配对' }) {
        Column() {
          if (this.status === 'idle') {
            // 取景框：暗底 + 品牌渐变中央框 + 扫描线（点击即调起系统扫码）
            Stack() {
              // 中央取景框（品牌渐变描边）
              Column()
                .width(180)
                .height(180)
                .borderRadius(16)
                .border({ width: 1.5, color: this.sm.getColor('border') })
                .linearGradient({
                  angle: 135,
                  colors: this.sm.getBrandGradient()
                })
                .opacity(0.9)
                .markAnchor({ x: '50%', y: '50%' })
                .position({ x: '50%', y: '50%' })

              // 扫描线（青色，上下往复）
              Column()
                .width('72%')
                .height(2)
                .borderRadius(2)
                .backgroundColor(this.sm.getColor('accent'))
                .shadow({ radius: 14, color: 'rgba(34,211,238,0.80)' })
                .markAnchor({ x: '50%', y: '50%' })
                .position({ x: '50%', y: this.scanPhase ? '62%' : '38%' })
                .animation({ duration: 1300, curve: Curve.EaseInOut })
            }
            .width('100%')
            .height(280)
            .borderRadius(22)
            .clip(true)
            .backgroundColor('rgba(19,26,46,0.9)')
            .onClick(() => { this.handleScan(); })

            // 提示文案（设计 F2 .pair-tip 三句）
            Text('对准 PC 端「配对设备」二维码')
              .fontSize(this.sm.getFontSize('card_title'))
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_primary'))
              .textAlign(TextAlign.Center)
              .margin({ top: 20 })

            Text('扫码即完成 服务器建档 + 设备配对，无需手动录入地址\n配对后本机获得长期设备身份，重连免扫码')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .textAlign(TextAlign.Center)
              .lineHeight(20)
              .margin({ top: 6 })

            // 回退入口（设计 .code-fallback）
            Row() {
              AppIcon({ name: 'edit', iconSize: 15, color: this.sm.getColor('primary') })
              Text('二维码不可用？手动输入 6 位配对码')
                .fontSize(this.sm.getFontSize('body_sm'))
                .fontColor(this.sm.getColor('primary'))
                  .margin({ left: 8 })
            }
            .width('100%')
            .justifyContent(FlexAlign.Center)
            .padding({ top: 12, bottom: 12 })
            .borderRadius(14)
            .backgroundColor(this.sm.getColor('primary_soft'))
            .border({ width: 1, color: this.sm.getColor('primary') })
            .margin({ top: 16 })
            .onClick(() => { this.mode = 'input'; this.resetToIdle(); })
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
              onTap: () => { this.resetToIdle(); }
            })
              .margin({ top: this.sm.getSpacing('sm') })
          }
        }
        .width('100%')
        .alignItems(HorizontalAlign.Center)
      }
    }
    .width('100%')
  }

  // ===========================================================================
  // 输入配对码区构建器
  // ===========================================================================
  @Builder
  buildInputArea() {
    Column() {
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
            // 真机（OpenHarmony-7.0.0.111）实测：TextInput 默认字体把数字渲染成异形
            // （1→´、4→∠、3/8→Ɛ），而 Text 渲染数字正常——故改为「隐形 TextInput 收输入
            // + Text 显示 cells 状态」：显示与提交同源（都来自 this.cells），
            // 不再依赖 TextInput 的字形渲染。
            Row() {
              ForEach([0, 1, 2, 3, 4, 5], (i: number) => {
                Stack() {
                  Text(this.cells[i])
                    .fontSize(22)
                    .fontWeight(FontWeight.Medium)
                    .fontColor(this.sm.getColor('text_primary'))
                  TextInput({ text: this.cells[i], placeholder: '' })
                    .type(InputType.Normal)
                    .maxLength(1)
                    .fontSize(22)
                    .fontColor(Color.Transparent)
                    .caretColor(Color.Transparent)
                    .textAlign(TextAlign.Center)
                    .width('100%')
                    .height('100%')
                    .key(`pairing_cell_${i}`)
                    .enabled(this.status !== 'waiting')
                    .onFocus(() => { this.focusedCell = i; })
                    .onBlur(() => {
                      if (this.focusedCell === i) {
                        this.focusedCell = -1;
                      }
                    })
                    .onChange((v: string) => { this.onCellChange(i, v); })
                }
                .width(40)
                .height(50)
                .margin({ left: i === 0 ? 0 : 4, right: 4 })
                .borderRadius(this.sm.getRadius('sm'))
                .border({
                  width: 1,
                  color: this.focusedCell === i
                    ? this.sm.getColor('primary')
                    : this.sm.getColor('border')
                })
                .backgroundColor(Color.Transparent)
                .alignContent(Alignment.Center)
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
                onTap: () => { this.retryInput(); }
              })
            } else {
              // 待操作：确认配对按钮（code 不足 6 位时禁用）
              GlassButton({
                text: '确认配对',
                type: 'primary',
                block: true,
                disabled: this.code.length !== CODE_LENGTH,
                onTap: () => { this.confirmPairing(); }
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
    }
    .width('100%')
  }
}
