/**
 * AgentSwitcher - Agent 切换器
 *
 * 职责：基于 GlassComponent 提供横向滚动的 Agent 胶囊列表，支持当前高亮、点击切换
 * 设计：外层 GlassComponent 容器内嵌横向 Scroll + Row；
 *       每个 Agent 一个胶囊（小尺寸 GlassComponent），当前 Agent primary 高亮，其余呈现玻璃色
 *
 * 用法：
 *   AgentSwitcher({
 *     currentAgentId: 'a1',
 *     agents: agentList,
 *     onSwitch: (id: string) => { this.currentId = id; }
 *   })
 */

import { Agent } from '../../libs/types';
import { StyleManager } from '../../libs/style/StyleManager';
import { Logger } from '../../libs/logger/Logger';

// 样式单例
const sm = StyleManager.getInstance();
// 日志单例
const logger = Logger.getInstance();

@Component
export struct AgentSwitcher {
  // 当前 Agent ID（用于高亮判定）
  @Prop currentAgentId: string = '';
  // Agent 列表
  @Prop agents: Array<Agent> = [];
  // 切换回调
  onSwitch: (agentId: string) => void = () => {};

  // 截取名称前 4 字符（超出部分截断）
  private getDisplayName(name: string): string {
    if (!name) return '';
    return name.length > 4 ? name.substring(0, 4) : name;
  }

  build() {
    GlassComponent({
      glassStyle: GlassStyle.BLUR_THIN,
      blurRadius: 20,
      colorScheme: GlassColorScheme.LIGHT
    }) {
      Scroll() {
        Row({ space: sm.getSpacing('sm') }) {
          ForEach(this.agents, (agent: Agent) => {
            this.buildCapsule(agent);
          }, (agent: Agent) => agent.id)
        }
        .padding(sm.getSpacing('sm'))
        .alignItems(VerticalAlign.Center)
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%')
    }
    .borderRadius(sm.getRadius('lg'))
  }

  // 单个 Agent 胶囊：使用小尺寸 GlassComponent 包装
  @Builder
  buildCapsule(agent: Agent) {
    GlassComponent({
      glassStyle: GlassStyle.BLUR_THIN,
      blurRadius: 10,
      colorScheme: GlassColorScheme.LIGHT
    }) {
      Text(this.getDisplayName(agent.name))
        .fontSize(14)
        .fontColor(agent.id === this.currentAgentId ? '#ffffff' : sm.getColor('text_primary'))
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .padding({ left: sm.getSpacing('sm'), right: sm.getSpacing('sm'), top: 6, bottom: 6 })
    }
    .borderRadius(sm.getRadius('full'))
    // 当前 Agent 用 primary 色覆盖玻璃背景；其余保持透明以呈现玻璃质感
    .backgroundColor(agent.id === this.currentAgentId ? sm.getColor('primary') : Color.Transparent)
    .onClick(() => {
      logger.info('AgentSwitcher', `切换 Agent: ${agent.id}`);
      this.onSwitch(agent.id);
    })
  }
}
