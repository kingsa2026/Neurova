package top.neurova.mobile.feature.chat

/**
 * 协作拓扑入口可见性判定（纯函数，JVM 可测；对齐鸿蒙端 SwarmFlowGate 同名门）。
 *
 * 产品裁定（2026-11-24）：协作拓扑图只在**存在协作**时才出现，默认以浮动图标
 * 形态悬浮于消息区右下角，点击图标才展开面板——常态不占聊天版面。
 * 本门是入口可见性的唯一判定源：
 *   - 无协作（无 run 节点且无审批/候选卡）→ 面板与图标一并不出现；
 *   - 有协作且折叠 → 仅浮动图标；
 *   - 有协作且已展开 → 面板展开（图标退场）。
 */

/** 是否存在协作：有 run 节点，或仅有审批/候选卡（run 已收敛但留痕） */
fun swarmHasCollab(runCount: Int, cardCount: Int): Boolean = runCount > 0 || cardCount > 0

/** 浮动图标可见：有协作且面板未展开（展开后面板本体接管入口） */
fun showSwarmFloatingIcon(hasCollab: Boolean, expanded: Boolean): Boolean = hasCollab && !expanded
