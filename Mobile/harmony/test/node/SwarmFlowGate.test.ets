/**
 * SwarmFlowGate 单测（Node 直跑）：协作拓扑入口可见性判定
 *
 * 背景：产品裁定——协作拓扑图只在**存在协作**时才出现，默认以浮动图标
 * 形态悬浮于消息区，点击图标才展开面板。门是入口可见性的唯一判定源：
 * 无协作（无 run 且无审批/候选卡）→ 一律不可见；有协作且折叠 → 浮动图标；
 * 有协作且已展开 → 图标本体。
 */

import { showSwarmFloatingIcon, swarmHasCollab } from '../../entry/src/main/ets/components/chat/SwarmFlowGate';
import { check, source } from './Harness';

source('协作拓扑入口门——无协作不显示，有协作默认浮动图标，点击展开');

// 无协作：run 与审批/候选卡都为 0 → 不存在协作
check('无 run 无卡 → 不算有协作', !swarmHasCollab(0, 0));
// 有 run（哪怕 1 个）即存在协作
check('有 run → 有协作', swarmHasCollab(1, 0));
check('多个 run → 有协作', swarmHasCollab(3, 0));
// 只有审批/候选卡（无 run 节点）也算有协作
check('仅审批/候选卡 → 有协作', swarmHasCollab(0, 2));

// 浮动图标：有协作且未展开才显示
check('有协作+折叠 → 显示浮动图标', showSwarmFloatingIcon(true, false));
check('有协作+已展开 → 不显示图标（面板展开）', !showSwarmFloatingIcon(true, true));
check('无协作+折叠 → 不显示图标', !showSwarmFloatingIcon(false, false));
check('无协作+已展开 → 不显示图标', !showSwarmFloatingIcon(false, true));
