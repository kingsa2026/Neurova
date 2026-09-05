// 主窗口逻辑：欢迎页 → 调 NSIS /S 静默内核（进度映射）→ 完成页
// 安装逻辑零重写：icacls 授权/卸载器/重装检测/管理员首装写入全在 NSIS 模板里
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media.Imaging;
using Microsoft.Win32;

namespace Neurova.Installer
{
    public partial class MainWindow : Window
    {
        private const string NsisKernel = "Neurova-kernel-setup.exe";
        private const string TermsUrl = "https://www.neurova.top/terms";
        private Process _installProc;
        private bool _customMode;

        public int ExitCode { get; private set; }

        public MainWindow()
        {
            InitializeComponent();
            LoadLogo();
            PathBox.Text = DefaultInstallDir();
            CustomLink.MouseLeftButtonUp += OnCustomClick;
        }

        private void LoadLogo()
        {
            try
            {
                var iconPath = System.IO.Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "neurova-icon.png");
                if (File.Exists(iconPath))
                    LogoImage.Source = new BitmapImage(new Uri(iconPath));
            }
            catch { /* Logo 缺失仅降级观感 */ }
        }

        private static string DefaultInstallDir()
        {
            // 复刻 NSIS 模板 perMachine 默认：优先历史安装目录
            var prev = (string)Registry.GetValue(
                @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Neurova",
                "InstallLocation", null);
            if (!string.IsNullOrEmpty(prev) && Directory.Exists(prev))
                return prev;
            return @"D:\Program Files\Neurova";
        }

        private void OnEulaChanged(object sender, RoutedEventArgs e)
            => InstallBtn.IsEnabled = EulaCheck.IsChecked == true;

        private void OnEulaLinkClick(object sender, MouseButtonEventArgs e)
        {
            try { Process.Start(new ProcessStartInfo(TermsUrl) { UseShellExecute = true }); }
            catch { /* 浏览器打开失败静默 */ }
        }

        private void OnBrowseClick(object sender, RoutedEventArgs e)
        {
            var dlg = new System.Windows.Forms.FolderBrowserDialog
            {
                SelectedPath = PathBox.Text,
                Description = "选择 Neurova 安装位置",
            };
            if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                PathBox.Text = dlg.SelectedPath;
        }

        private void OnCustomClick(object sender, MouseButtonEventArgs e)
        {
            // 自定义安装 = 显示路径可编辑（一键模式保持只读观感）
            _customMode = !_customMode;
            PathBox.IsReadOnly = !_customMode;
            CustomLink.Text = _customMode ? "返回快速安装 ›" : "自定义安装 ›";
        }

        private void OnInstallClick(object sender, RoutedEventArgs e)
        {
            if (EulaCheck.IsChecked != true) return;
            StartInstall(PathBox.Text.Trim());
        }

        private void StartInstall(string targetDir)
        {
            var kernel = System.IO.Path.Combine(AppDomain.CurrentDomain.BaseDirectory, NsisKernel);
            if (!File.Exists(kernel))
            {
                MessageBox.Show($"安装内核缺失：{NsisKernel}", "Neurova",
                    MessageBoxButton.OK, MessageBoxImage.Error);
                return;
            }

            PageWelcome.Visibility = Visibility.Collapsed;
            PageProgress.Visibility = Visibility.Visible;
            ProgressTitle.Text = "正在安装…";

            // NSIS /S 静默 + /D= 目标目录（必须无引号、末尾不带反斜杠）
            var psi = new ProcessStartInfo
            {
                FileName = kernel,
                Arguments = "/S /D=" + targetDir,
                UseShellExecute = true,
                Verb = "runas",
                CreateNoWindow = true,
            };

            try
            {
                _installProc = Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"无法启动安装内核：{ex.Message}", "Neurova",
                    MessageBoxButton.OK, MessageBoxImage.Error);
                PageWelcome.Visibility = Visibility.Visible;
                PageProgress.Visibility = Visibility.Collapsed;
                return;
            }

            // 进度模拟 + 内核退出检测（NSIS /S 无 stdout 进度流；
            // 产物体积已知，按目录增长映射真实进度）
            var pool = ThreadPool.QueueUserWorkItem(_ =>
            {
                var sw = Stopwatch.StartNew();
                while (true)
                {
                    Thread.Sleep(400);
                    if (_installProc == null) return;
                    _installProc.Refresh();
                    if (_installProc.HasExited)
                    {
                        Dispatcher.Invoke(FinishInstall);
                        return;
                    }
                    // 目录增长 → 进度（安装总量 ~1.9GB，上限 95% 留给收尾段）
                    long bytes = DirSize(new DirectoryInfo(targetDir));
                    long total = 1_900_000_000L;
                    int pct = (int)Math.Min(95, bytes * 100 / total);
                    int elapsedHint = (int)Math.Min(95, sw.ElapsedMilliseconds / 600);
                    int shown = Math.Max(pct, elapsedHint);
                    Dispatcher.Invoke(() =>
                    {
                        ProgressBar.Value = shown;
                        ProgressDetail.Text = $"已写入 {bytes / 1024 / 1024} MB";
                    });
                }
            });
        }

        private static long DirSize(DirectoryInfo dir)
        {
            long total = 0;
            try
            {
                foreach (var f in dir.EnumerateFiles("*", System.IO.SearchOption.AllDirectories))
                {
                    try { total += f.Length; } catch { }
                }
            }
            catch { }
            return total;
        }

        private void FinishInstall()
        {
            var exit = _installProc?.ExitCode ?? -1;
            if (exit == 0)
            {
                ProgressBar.Value = 100;
                PageProgress.Visibility = Visibility.Collapsed;
                PageDone.Visibility = Visibility.Visible;
            }
            else
            {
                ProgressTitle.Text = "安装中断";
                ProgressDetail.Text = $"安装内核退出码 {exit}，可重新运行安装程序。";
                PageWelcome.Visibility = Visibility.Visible;
                PageProgress.Visibility = Visibility.Collapsed;
            }
        }

        private void OnFinishClick(object sender, RoutedEventArgs e)
        {
            if (RunNowCheck.IsChecked == true)
            {
                var exe = System.IO.Path.Combine(PathBox.Text, "Neurova.exe");
                if (File.Exists(exe))
                {
                    try { Process.Start(new ProcessStartInfo(exe) { UseShellExecute = true }); }
                    catch { }
                }
            }
            ExitCode = 0;
            Close();
        }
    }
}
