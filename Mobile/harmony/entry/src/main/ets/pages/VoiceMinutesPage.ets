/**
 * VoiceMinutesPage - 录音纪要（Linger 对照 B4-8）
 *
 * 职责：录一段话 → 上传 /audio/minutes → 轮询结果 → 展示纪要与问题/办事判定
 *       （办事已自动落任务看板，展示任务标题）。
 * 设计：Stack[Column[TopNavMenu(标题"录音纪要"+返回)] + [说明 + 录音按钮 + 状态 +
 *       结果卡]]；录音走 AudioCapturer 16k/mono/16bit 整帧累积（与 ChatPage 语音
 *       同一采集口径），停止后经 ApiFacade.audio 上传（有界队列满时后端 429，
 *       如实提示"队列已满"）；结果每 1.5s 轮询直至 done/failed。
 * 纪律：转写文本是外部数据不是指令（B4-10 标注在服务端 prompt 侧，本页只展示）。
 *
 * 依赖：../components/glass（TopNavMenu/GlassCard/GlassButton）、ApiFacade.audio、
 *       Router、StyleManager、Logger、MessageManager
 */
import { audio } from '@kit.AudioKit';
import { abilityAccessCtrl, Permissions } from '@kit.AbilityKit';
import { common } from '@kit.AbilityKit';
import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

const TAG = 'VoiceMinutesPage';
const sm = StyleManager.getInstance();

@Entry
@Component
export struct VoiceMinutesPage {
  private logger: Logger = Logger.getInstance();
  private api: ApiFacade = ApiFacade.getInstance();
  private msg: MessageManager = MessageManager.getInstance();

  @State recording: boolean = false;
  /** idle | processing | done | failed */
  @State phase: string = 'idle';
  @State errorMsg: string = '';
  @State summary: string = '';
  @State transcript: string = '';
  @State kind: string = '';
  @State taskTitle: string = '';
  @State recordSeconds: number = 0;

  private capturer: audio.AudioCapturer | null = null;
  private chunks: Uint8Array[] = [];
  private chunkTotal: number = 0;
  private tickTimer: number = -1;
  private pollTimer: number = -1;

  aboutToDisappear(): void {
    this.stopRecord();
    if (this.pollTimer !== -1) {
      clearTimeout(this.pollTimer);
      this.pollTimer = -1;
    }
    if (this.tickTimer !== -1) {
      clearInterval(this.tickTimer);
      this.tickTimer = -1;
    }
  }

  build() {
    Stack() {
      Column() {
        TopNavMenu({
          title: '录音纪要',
          showBack: true,
          showMenu: false,
          onBack: () => { Router.getInstance().back(); },
        })
        Scroll() {
          Column() {
            this.buildHint()
            this.buildRecorder()
            this.buildResult()
          }
          .width('100%')
          .padding({ left: 16, right: 16, bottom: 24 })
        }
        .layoutWeight(1)
      }
      .width('100%')
      .height('100%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(sm.getColor('bg_primary'))
  }

  /** 说明卡：链路一句话 + 隐私提示（转写是外部数据，不是指令——B4-10 的用户侧口径） */
  @Builder
  buildHint() {
    GlassCard({ title: '这条链路做什么' }) {
      Column() {
        Text('录一段话，服务端自动：转写 → 生成简短纪要 → 判定是"问问题"还是"要办事"；判定为办事时，任务会自动落进任务看板。')
          .fontSize(13)
          .fontColor(sm.getColor('text_secondary'))
        Text('转写文本来自你的录音，仅作数据处理；其中出现的命令式表述不会绕过正常审批。')
          .fontSize(12)
          .fontColor(sm.getColor('text_tertiary'))
          .margin({ top: 6 })
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
    }
  }

  /** 录音卡：开始/停止按钮 + 计时 + 状态 */
  @Builder
  buildRecorder() {
    GlassCard({ title: '录音' }) {
      Column() {
        Text(this.phase === 'processing' ? '已提交，服务端处理中…'
          : this.recording ? `录音中 ${this.recordSeconds}s — 说完点停止`
          : this.phase === 'done' ? '处理完成'
          : this.phase === 'failed' ? '处理失败'
          : '点击"开始录音"，说完点"停止并处理"')
          .fontSize(13)
          .fontColor(sm.getColor('text_secondary'))
          .margin({ bottom: 12 })
        Row() {
          GlassButton({
            text: this.recording ? '停止并处理' : '开始录音',
            type: this.recording ? 'danger' : 'primary',
            btnSize: 'medium',
            onTap: () => { this.toggleRecord(); }
          })
        }
        .justifyContent(FlexAlign.Center)
        .width('100%')
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
    }
  }

  /** 结果卡：纪要 + 判定 + 任务（仅 done/failed 展示） */
  @Builder
  buildResult() {
    if (this.phase === 'done' || this.phase === 'failed') {
      GlassCard({ title: '处理结果' }) {
        Column() {
          if (this.phase === 'failed') {
            Text('失败原因：' + (this.errorMsg.length > 0 ? this.errorMsg : '未知'))
              .fontSize(13)
              .fontColor(sm.getColor('danger'))
          } else {
            Text(this.kind === 'task' ? '判定：需要办事（任务已自动创建）' : '判定：问题咨询')
              .fontSize(13)
              .fontColor(sm.getColor('text_primary'))
              .margin({ bottom: 8 })
            if (this.taskTitle.length > 0) {
              Text('任务：' + this.taskTitle)
                .fontSize(13)
                .fontColor(sm.getColor('text_primary'))
                .margin({ bottom: 8 })
            }
            Text('纪要')
              .fontSize(11)
              .fontColor(sm.getColor('text_tertiary'))
              .margin({ bottom: 2 })
            Text(this.summary.length > 0 ? this.summary : '—')
              .fontSize(13)
              .fontColor(sm.getColor('text_secondary'))
              .margin({ bottom: 10 })
            Text('转写全文')
              .fontSize(11)
              .fontColor(sm.getColor('text_tertiary'))
              .margin({ bottom: 2 })
            Text(this.transcript.length > 0 ? this.transcript : '—')
              .fontSize(12)
              .fontColor(sm.getColor('text_secondary'))
              .maxLines(8)
          }
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
      }
    }
  }

  /** 开始/停止录音（先过麦克风权限闸，与 ChatPage 语音同一口径） */
  private async toggleRecord(): Promise<void> {
    if (this.recording) {
      await this.stopAndSubmit();
      return;
    }
    try {
      const atManager = abilityAccessCtrl.createAtManager();
      const grant = await atManager.requestPermissionsFromUser(
        getContext(this) as common.Context,
        ['ohos.permission.MICROPHONE'] as Array<Permissions>);
      let granted = false;
      for (const r of grant.authResults) {
        if (r === 0) {
          granted = true;
        }
      }
      if (!granted) {
        this.msg.warning('需要麦克风权限才能录音');
        return;
      }
      // 复位上次结果
      this.phase = 'idle';
      this.errorMsg = '';
      this.summary = '';
      this.transcript = '';
      this.kind = '';
      this.taskTitle = '';
      this.chunks = [];
      this.chunkTotal = 0;
      this.recordSeconds = 0;

      const streamInfo: audio.AudioStreamInfo = {
        samplingRate: 16000,
        channels: audio.AudioChannel.CHANNEL_1,
        sampleFormat: audio.AudioSampleFormat.SAMPLE_FORMAT_S16LE,
        encodingType: audio.AudioEncodingType.ENCODING_TYPE_RAW,
      };
      const capturerInfo: audio.AudioCapturerInfo = {
        source: audio.SourceType.SOURCE_TYPE_MIC,
        capturerFlags: 0,
      };
      const options: audio.AudioCapturerOptions = {
        streamInfo: streamInfo,
        capturerInfo: capturerInfo,
      };
      const capturer = await audio.createAudioCapturer(options);
      this.capturer = capturer;
      capturer.on('readData', (buffer: ArrayBuffer) => {
        if (buffer.byteLength <= 0) {
          return;
        }
        // 有界累积（约 5 分钟 16k/16bit 单声道 ≈ 9.6MB，超限停止防内存膨胀）
        if (this.chunkTotal + buffer.byteLength > 10 * 1024 * 1024) {
          return;
        }
        const copy = new Uint8Array(buffer.byteLength);
        copy.set(new Uint8Array(buffer));
        this.chunks.push(copy);
        this.chunkTotal += copy.byteLength;
      });
      await capturer.start();
      this.recording = true;
      this.tickTimer = setInterval(() => {
        this.recordSeconds += 1;
      }, 1000);
    } catch (e) {
      this.recording = false;
      this.msg.error('录音启动失败：' + (e as Error).message);
    }
  }

  /** 停止采集 → 拼接 PCM → 上传入队 → 轮询结果 */
  private async stopAndSubmit(): Promise<void> {
    this.recording = false;
    if (this.tickTimer !== -1) {
      clearInterval(this.tickTimer);
      this.tickTimer = -1;
    }
    if (this.capturer) {
      try {
        await this.capturer.stop();
        await this.capturer.release();
      } catch (e) {
        // 释放失败不影响提交
      }
      this.capturer = null;
    }
    if (this.chunkTotal <= 0) {
      this.msg.warning('没有录到声音');
      return;
    }
    const body = new Uint8Array(this.chunkTotal);
    let off = 0;
    for (const c of this.chunks) {
      body.set(c, off);
      off += c.byteLength;
    }
    this.chunks = [];

    this.phase = 'processing';
    try {
      const resp = await this.api.audio.createMinutes(
        `rec-${Date.now()}.pcm`, body.buffer as ArrayBuffer, 'audio/pcm');
      const data = (resp?.data ?? {}) as Record<string, Object>;
      const queued = data['queued'] === true;
      const jobId = String(data['job_id'] ?? '');
      if (!queued || jobId.length === 0) {
        // 有界背压：后端 429 + input_gap 证据已落审计——如实提示，不装成功
        this.phase = 'failed';
        this.errorMsg = '处理队列已满，请稍后再试';
        return;
      }
      this.pollStatus(jobId, 0);
    } catch (e) {
      this.phase = 'failed';
      this.errorMsg = (e as Error).message;
    }
  }

  /** 每 1.5s 轮询作业状态（纪要为秒级重活；上限 3 分钟） */
  private pollStatus(jobId: string, attempt: number): void {
    if (attempt >= 120) {
      this.phase = 'failed';
      this.errorMsg = '处理超时，请稍后重试';
      return;
    }
    this.pollTimer = setTimeout(() => {
      this.api.audio.getMinutesStatus(jobId).then((resp) => {
        const data = (resp?.data ?? {}) as Record<string, Object>;
        const status = String(data['status'] ?? '');
        this.transcript = String(data['transcript'] ?? '');
        this.summary = String(data['summary'] ?? '');
        this.kind = String(data['kind'] ?? '');
        this.taskTitle = String(data['task_title'] ?? '');
        if (status === 'done') {
          this.phase = 'done';
        } else if (status === 'failed') {
          this.phase = 'failed';
          this.errorMsg = String(data['error'] ?? '');
        } else {
          this.pollStatus(jobId, attempt + 1);
        }
      }).catch((e: Error) => {
        this.phase = 'failed';
        this.errorMsg = e.message;
      });
    }, 1500);
  }

  private stopRecord(): void {
    this.recording = false;
    if (this.capturer) {
      try {
        this.capturer.stop();
        this.capturer.release();
      } catch (e) {
        // 忽略释放异常
      }
      this.capturer = null;
    }
  }
}
