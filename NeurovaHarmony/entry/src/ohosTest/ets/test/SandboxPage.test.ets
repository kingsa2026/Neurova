// SandboxPage 沙盒环境页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：SandboxViewHelper 视图模型行为（状态颜色/图标/标签映射、
//           CPU 限制格式化、内存限制格式化、端口列表格式化、过期时间格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 SandboxPage.ets 导出的 SandboxViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { SandboxViewHelper } from '../../../../main/ets/pages/SandboxPage';

export default function sandboxPageTest() {
  describe('SandboxPage', () => {
    // ========== 切片1: getStatusColor - created → info ==========

    it('status_color_created_returns_info', 0, () => {
      expect(SandboxViewHelper.getStatusColor('created')).assertEqual('info');
    });

    // ========== 切片2: getStatusColor - running → success ==========

    it('status_color_running_returns_success', 0, () => {
      expect(SandboxViewHelper.getStatusColor('running')).assertEqual('success');
    });

    // ========== 切片3: getStatusColor - stopped → text_secondary ==========

    it('status_color_stopped_returns_text_secondary', 0, () => {
      expect(SandboxViewHelper.getStatusColor('stopped')).assertEqual('text_secondary');
    });

    // ========== 切片4: getStatusColor - error → error ==========

    it('status_color_error_returns_error', 0, () => {
      expect(SandboxViewHelper.getStatusColor('error')).assertEqual('error');
    });

    // ========== 切片5: getStatusColor - expired → warning ==========

    it('status_color_expired_returns_warning', 0, () => {
      expect(SandboxViewHelper.getStatusColor('expired')).assertEqual('warning');
    });

    // ========== 切片6: getStatusIcon - created 返回 emoji ==========

    it('status_icon_created_returns_emoji', 0, () => {
      expect(SandboxViewHelper.getStatusIcon('created').length > 0).assertTrue();
    });

    // ========== 切片7: getStatusIcon - running 返回 emoji ==========

    it('status_icon_running_returns_emoji', 0, () => {
      expect(SandboxViewHelper.getStatusIcon('running').length > 0).assertTrue();
    });

    // ========== 切片8: getStatusIcon - expired 返回 emoji ==========

    it('status_icon_expired_returns_emoji', 0, () => {
      expect(SandboxViewHelper.getStatusIcon('expired').length > 0).assertTrue();
    });

    // ========== 切片9: getLabel - created → 已创建 ==========

    it('label_created_returns_已创建', 0, () => {
      expect(SandboxViewHelper.getStatusLabel('created')).assertEqual('已创建');
    });

    // ========== 切片10: getLabel - running → 运行中 ==========

    it('label_running_returns_运行中', 0, () => {
      expect(SandboxViewHelper.getStatusLabel('running')).assertEqual('运行中');
    });

    // ========== 切片11: getLabel - stopped → 已停止 ==========

    it('label_stopped_returns_已停止', 0, () => {
      expect(SandboxViewHelper.getStatusLabel('stopped')).assertEqual('已停止');
    });

    // ========== 切片12: getLabel - error → 错误 ==========

    it('label_error_returns_错误', 0, () => {
      expect(SandboxViewHelper.getStatusLabel('error')).assertEqual('错误');
    });

    // ========== 切片13: getLabel - expired → 已过期 ==========

    it('label_expired_returns_已过期', 0, () => {
      expect(SandboxViewHelper.getStatusLabel('expired')).assertEqual('已过期');
    });

    // ========== 切片14: formatCpuLimit - 整数核数 ==========

    it('format_cpu_limit_integer', 0, () => {
      expect(SandboxViewHelper.formatCpuLimit(2)).assertEqual('2.0 核');
    });

    // ========== 切片15: formatCpuLimit - 小数核数 ==========

    it('format_cpu_limit_decimal', 0, () => {
      expect(SandboxViewHelper.formatCpuLimit(0.5)).assertEqual('0.5 核');
    });

    // ========== 切片16: formatCpuLimit - 1 核 ==========

    it('format_cpu_limit_one', 0, () => {
      expect(SandboxViewHelper.formatCpuLimit(1)).assertEqual('1.0 核');
    });

    // ========== 切片17: formatMemoryLimit - 小于 1024 MB ==========

    it('format_memory_limit_under_1024_returns_mb', 0, () => {
      expect(SandboxViewHelper.formatMemoryLimit(512)).assertEqual('512MB');
    });

    // ========== 切片18: formatMemoryLimit - 等于 1024 → '1.0GB' ==========

    it('format_memory_limit_1024_returns_gb', 0, () => {
      expect(SandboxViewHelper.formatMemoryLimit(1024)).assertEqual('1.0GB');
    });

    // ========== 切片19: formatMemoryLimit - 大于 1024 MB ==========

    it('format_memory_limit_over_1024_returns_gb', 0, () => {
      expect(SandboxViewHelper.formatMemoryLimit(2048)).assertEqual('2.0GB');
    });

    // ========== 切片20: formatMemoryLimit - 小数 GB ==========

    it('format_memory_limit_decimal_gb', 0, () => {
      expect(SandboxViewHelper.formatMemoryLimit(1536)).assertEqual('1.5GB');
    });

    // ========== 切片21: formatPorts - 空数组 → '无' ==========

    it('format_ports_empty_returns_无', 0, () => {
      expect(SandboxViewHelper.formatPorts([])).assertEqual('无');
    });

    // ========== 切片22: formatPorts - 单个端口 ==========

    it('format_ports_single_returns_port', 0, () => {
      expect(SandboxViewHelper.formatPorts([8080])).assertEqual('8080');
    });

    // ========== 切片23: formatPorts - 两个端口 ==========

    it('format_ports_two_returns_joined', 0, () => {
      expect(SandboxViewHelper.formatPorts([8080, 9000])).assertEqual('8080, 9000');
    });

    // ========== 切片24: formatPorts - 三个端口 ==========

    it('format_ports_three_returns_all', 0, () => {
      expect(SandboxViewHelper.formatPorts([80, 443, 8080])).assertEqual('80, 443, 8080');
    });

    // ========== 切片25: formatPorts - 四个端口截断 ==========

    it('format_ports_four_truncates', 0, () => {
      const result = SandboxViewHelper.formatPorts([80, 443, 8080, 9000]);
      // 最多显示前 3 个 + '...'
      expect(result).assertEqual('80, 443, 8080...');
    });

    // ========== 切片26: formatExpiry - 已过期 ==========

    it('format_expiry_past_returns_已过期', 0, () => {
      // 过去时间
      const past = '2020-01-01T00:00:00Z';
      const result = SandboxViewHelper.formatExpiry(past);
      expect(result).assertEqual('已过期');
    });

    // ========== 切片27: formatExpiry - 未来 5 小时 ==========

    it('format_expiry_future_hours', 0, () => {
      // 当前时间 + 5 小时
      const future = new Date(Date.now() + 5 * 3600 * 1000).toISOString();
      const result = SandboxViewHelper.formatExpiry(future);
      // 应包含 '小时后过期'
      expect(result.indexOf('小时后过期') >= 0).assertTrue();
    });

    // ========== 切片28: formatExpiry - 未来 2 天 ==========

    it('format_expiry_future_days', 0, () => {
      // 当前时间 + 2 天
      const future = new Date(Date.now() + 2 * 86400 * 1000).toISOString();
      const result = SandboxViewHelper.formatExpiry(future);
      // 应包含 '天后过期'
      expect(result.indexOf('天后过期') >= 0).assertTrue();
    });

    // ========== 切片29: formatExpiry - 无效时间 → '—' ==========

    it('format_expiry_invalid_returns_dash', 0, () => {
      expect(SandboxViewHelper.formatExpiry('invalid-date')).assertEqual('—');
    });
  });
}
