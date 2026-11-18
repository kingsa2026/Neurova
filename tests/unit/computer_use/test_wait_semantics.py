"""P3-8（电脑操控对照评测）：等待语义钉死——「动作后必补拍」是契约。

两边取舍不同且都成立：参照系删掉独立 wait 工具（观察内建 settle）；
Neurova 以「成功动作后 0.5s 自动补拍刷新截图」承担同一语义（R0-3）。
本文件把这条语义钉成契约：凡动真实输入的前台工具必须声明补拍
（interactive_desktop），观察/命令面一律不得补拍——防止日后新增工具漏配或滥配。
"""

from neurova.tool_executor import ACTION_REFRESH_DELAY_SECONDS, computerActionRefreshTools


class TestRefreshSemanticsPinned:
    def test_foreground_input_family_must_refresh(self):
        """动真实输入设备的前台工具：动作后必补拍（模型/人都要看到结果画面）。"""
        from neurova.computer_use import foregroundDesktopTools

        missing = foregroundDesktopTools() - computerActionRefreshTools()
        assert not missing, f"前台输入族漏配补拍声明（interactive_desktop）：{sorted(missing)}"

    def test_observation_and_command_faces_do_not_refresh(self):
        """观察/命令面不产画面变化，补拍无意义——滥配即红。"""
        for name in (
            "computer_screenshot",
            "computer_dom_snapshot",
            "computer_som_snapshot",
            "computer_list_windows",
            "computer_shell",
            "computer_ssh_exec",
        ):
            assert name not in computerActionRefreshTools(), name

    def test_refresh_delay_is_bounded_named_constant(self):
        """补拍延迟是具名常量且有界（0 < d ≤ 2s）——不许散落魔法数。"""
        assert 0 < ACTION_REFRESH_DELAY_SECONDS <= 2.0
