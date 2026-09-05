// Neurova 安装器界面壳（WiX/WPF 路线）
// 纯 C# 代码构建 UI（无 XAML）→ 系统 csc 直接编译，零 SDK 依赖。
// 界面：欢迎页（品牌 Hero/协议/路径/一键安装）→ 进度页 → 完成页。
// 安装内核 = NSIS /S 静默模式（icacls/卸载器/重装检测/管理员首装全复用）。
using System;
using System.IO;
using System.Windows;

namespace Neurova.Installer
{
    public static class Program
    {
        [STAThread]
        public static int Main(string[] args)
        {
            File.WriteAllText(
                Path.Combine(Path.GetTempPath(), "neurova-setup-log.txt"),
                "main-enter " + DateTime.Now.ToString("HH:mm:ss.fff") + Environment.NewLine);

            // 提权校验：perMachine 写 Program Files + icacls 必须管理员。
            // NEUROVA_SETUP_DEV=1 仅供 UI 开发迭代旁路（正式包不设此变量）。
            var devBypass = Environment.GetEnvironmentVariable("NEUROVA_SETUP_DEV") == "1";
            if (!devBypass && !new System.Security.Principal.WindowsPrincipal(
                    System.Security.Principal.WindowsIdentity.GetCurrent())
                .IsInRole(System.Security.Principal.WindowsBuiltInRole.Administrator))
            {
                File.AppendAllText(
                    Path.Combine(Path.GetTempPath(), "neurova-setup-log.txt"),
                    "not-admin, showing box" + Environment.NewLine);
                MessageBox.Show(
                    "请以管理员身份运行安装程序 / Please run the installer as administrator.",
                    "Neurova", MessageBoxButton.OK, MessageBoxImage.Warning);
                return 1;
            }

            File.AppendAllText(
                Path.Combine(Path.GetTempPath(), "neurova-setup-log.txt"),
                "admin ok, building window" + Environment.NewLine);
            var app = new Application { ShutdownMode = ShutdownMode.OnMainWindowClose };
            MainWindow win;
            try
            {
                win = new MainWindow();
            }
            catch (Exception ex)
            {
                File.AppendAllText(
                    Path.Combine(Path.GetTempPath(), "neurova-setup-log.txt"),
                    "CTOR CRASH: " + ex.GetType().Name + ": " + ex.Message + "\n"
                    + ex.StackTrace + Environment.NewLine);
                throw;
            }
            File.AppendAllText(
                Path.Combine(Path.GetTempPath(), "neurova-setup-log.txt"),
                "window built, running" + Environment.NewLine);
            app.Run(win);
            File.AppendAllText(
                Path.Combine(Path.GetTempPath(), "neurova-setup-log.txt"),
                "run-done exit" + Environment.NewLine);
            return win.ExitCode;
        }
    }
}
