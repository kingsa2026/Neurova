import { WsReliabilityState } from '../../entry/src/main/ets/libs/adapters/WsReliabilityState';
import { check, source } from './Harness';

source('P2-23 鸿蒙 WS 幂等、游标与快照重同步');

let state = new WsReliabilityState();
const frame = JSON.parse('{"type":"chat:chunk","content":"a\\\"b\\\\c\\n","seq":9}') as Record<string, Object>;
check('JSON 转义原样解码', frame['content'] === 'a"b\\c\n');
check('首帧接收', state.accept(frame));
check('旧 seq 拒绝', !state.accept({ 'type': 'chat:done', 'seq': 4 }));
check('游标取最大值', state.cursor === 9);
check('消息 ID 首次接收', state.accept({ 'type': 'chat:chunk', 'message_id': 'm1', 'seq': 10 }));
check('重复消息幂等', !state.accept({ 'type': 'chat:chunk', 'message_id': 'm1', 'seq': 11 }));
check('重复消息仍推进游标', state.cursor === 11);
state.reset();
check('快照重同步清游标', state.cursor === 0);
check('快照后允许重新接收业务 ID', state.accept({ 'type': 'chat:chunk', 'message_id': 'm1', 'seq': 1 }));
