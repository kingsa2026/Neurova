// Neurova 安装器（与前端登录页同款视觉：Cosmic 深色星空 + 玻璃拟态卡片）
// 三页：欢迎（Logo/协议/自定义折叠/立即安装）→ 管理员账号（两次密码+一致性
// 校验+权限警示）→ 进度 → 完成。安装内核 = NSIS /S（侧车优先，否则解压内嵌资源）。
// 语法上限 C# 5（系统 csc）：禁 $""、?.、using var、数字分隔符。
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using System.Windows.Shell;
using Microsoft.Win32;

namespace Neurova.Installer
{
    public class MainWindow : Window
    {
        private const string NsisKernel = "Neurova-kernel-setup.exe";
        private const string EmbeddedKernel = "Neurova.Installer.kernel-setup.exe";
        private const string EmbeddedLogo = "Neurova.Installer.neurova-logo.png";
        private const string TermsUrl = "https://www.neurova.top/terms";
        private const string PrivacyUrl = "https://www.neurova.top/privacy";
        // Cosmic 皮肤色板（styles/variables.css 对齐）
        private const string DeepBg = "#06080F";
        private const string CardBg = "#CC1A2236";   // 玻璃卡片（70% 不透明）
        private const string CardBorder = "#22FFFFFF";
        private const string Primary = "#6366F1";    // --nr-primary（cosmic dark）
        private const string TextMain = "#F2F5FF";
        private const string TextSub = "#96A5DC";

        private RadioButton _eulaRadio;
        private TextBox _pathBox;
        private Button _installBtn;
        private TextBlock _customToggle, _customArrow;
        private StackPanel _pageWelcome, _pageAdmin, _pageProgress, _pageDone;
        private TextBlock _progressTitle, _progressDetail;
        private ProgressBar _progressBar;
        private CheckBox _runNowCheck;
        private Border _customPanel;
        private TextBox _adminUser;
        private System.Windows.Controls.PasswordBox _adminPass, _adminPass2;
        private TextBlock _adminHint;
        private string _installTarget = "";
        private Process _installProc;
        private bool _kernelExtracted;
        private bool _isUpgrade;         // 检测到历史安装 → 升级模式：跳过管理员注册页
        public int ExitCode { get; private set; }

        private const string UninstallKey = @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Neurova";

        private static bool IsNeurovaInstalled()
        {
            try
            {
                if (Registry.GetValue(UninstallKey, "InstallLocation", null) != null) return true;
                if (Registry.GetValue(UninstallKey, "UninstallString", null) != null) return true;
                return Registry.GetValue(UninstallKey, "DisplayName", null) != null;
            }
            catch { return false; }
        }

        // VC++ 2015-2022 x64 运行库检测（后端 torch/编译扩展依赖）
        private static bool IsVcRedistInstalled()
        {
            try
            {
                var v = (string)Registry.GetValue(
                    @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                    "Version", null);
                if (v == null) return false;
                var parts = v.TrimStart('v').Split('.');
                int major = int.Parse(parts[0]);
                int minor = int.Parse(parts[1]);
                return major > 14 || (major == 14 && minor >= 30);
            }
            catch { return false; }
        }

        // 缺 VC++ → 从 aka.ms 官方源静默安装（/quiet；安装器已提权）
        // 返回 null=成功或本就存在；非 null=失败原因（不阻断安装，仅提示）
        private string EnsureVcRedist()
        {
            if (IsVcRedistInstalled()) return null;
            try
            {
                string dst = Path.Combine(Path.GetTempPath(), "vc_redist.x64.exe");
                using (var wc = new System.Net.WebClient())
                {
                    wc.DownloadFile("https://aka.ms/vs/17/release/vc_redist.x64.exe", dst);
                }
                var psi = new ProcessStartInfo
                {
                    FileName = dst,
                    Arguments = "/install /quiet /norestart",
                    UseShellExecute = true,
                };
                using (var p = Process.Start(psi))
                {
                    p.WaitForExit();
                    int code = p.ExitCode;
                    if (code == 0 || code == 3010 || code == 1638) return null;
                    return "vc_redist 退出码 " + code;
                }
            }
            catch (Exception ex)
            {
                return ex.Message;
            }
        }

        public MainWindow()
        {
            Width = 800; Height = 520;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            ResizeMode = ResizeMode.NoResize;
            WindowStyle = WindowStyle.None;
            Background = Brushes.Transparent;

            var chrome = new WindowChrome
            {
                CaptionHeight = 40,
                CornerRadius = new CornerRadius(10),
                GlassFrameThickness = new Thickness(0),
                ResizeBorderThickness = new Thickness(0),
                UseAeroCaptionButtons = false,
            };
            WindowChrome.SetWindowChrome(this, chrome);

            Content = BuildRootLayout();
            _pathBox.Text = DefaultInstallDir();
            _installBtn.IsEnabled = false;
            _isUpgrade = IsNeurovaInstalled();
        }

        // ---------- 布局骨架：星空底 + 居中玻璃卡 + 底部协议行 ----------
        private UIElement BuildRootLayout()
        {
            var outer = new Grid();
            var card = new Border
            {
                CornerRadius = new CornerRadius(10),
                Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString(DeepBg)),
                Effect = new DropShadowEffect
                {
                    BlurRadius = 28, ShadowDepth = 2, Opacity = 0.35, Color = Colors.Black,
                },
            };
            outer.Children.Add(card);

            var layout = new Grid();
            card.Child = layout;
            layout.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });  // 自定义折叠
            layout.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });  // 协议行

            layout.Children.Add(BuildStars());

            // 四页容器直接铺在星空底上（欢迎页无卡片；管理员页输入框各自带玻璃背板）
            var pages = new Grid();
            Grid.SetRow(pages, 0);
            layout.Children.Add(pages);

            _pageWelcome = BuildWelcomePage();
            _pageAdmin = BuildAdminPage();
            _pageProgress = BuildProgressPage();
            _pageDone = BuildDonePage();
            pages.Children.Add(_pageWelcome);
            pages.Children.Add(_pageAdmin);
            pages.Children.Add(_pageProgress);
            pages.Children.Add(_pageDone);

            _customPanel = BuildCustomPanel();
            Grid.SetRow(_customPanel, 1);
            _customPanel.Visibility = Visibility.Collapsed;
            layout.Children.Add(_customPanel);

            var footer = BuildFooterRow();
            Grid.SetRow(footer, 2);
            layout.Children.Add(footer);

            var caption = BuildCaptionButtons();
            Grid.SetRow(caption, 0);
            Grid.SetRowSpan(caption, 3);
            layout.Children.Add(caption);
            return outer;
        }

        private UIElement BuildStars()
        {
            var canvas = new Canvas { ClipToBounds = true };
            var rnd = new Random(42);   // 固定种子：星点布局稳定
            for (int i = 0; i < 70; i++)
            {
                double x = rnd.NextDouble() * 800;
                double y = rnd.NextDouble() * 520;
                double r = rnd.Next(1, 2);
                byte v = (byte)rnd.Next(60, 190);
                var star = new System.Windows.Shapes.Ellipse
                {
                    Width = r * 2,
                    Height = r * 2,
                    Fill = new SolidColorBrush(Color.FromRgb(v, v, (byte)Math.Min(255, v + 30))),
                };
                Canvas.SetLeft(star, x);
                Canvas.SetTop(star, y);
                canvas.Children.Add(star);
            }
            return canvas;
        }

        private UIElement BuildCaptionButtons()
        {
            var panel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 4, 6, 0),
            };
            // 附加属性不能用对象初始化器点语法（C# 限制），须 SetValue
            WindowChrome.SetIsHitTestVisibleInChrome(panel, true);
            panel.Children.Add(CaptionButton("—", delegate { WindowState = WindowState.Minimized; }));
            panel.Children.Add(CaptionButton("✕", delegate { Close(); }));
            return panel;
        }

        private TextBlock CaptionButton(string glyph, MouseButtonEventHandler onClick)
        {
            var tb = new TextBlock
            {
                Text = glyph,
                FontSize = 14,
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(TextSub)),
                Width = 40,
                Height = 32,
                TextAlignment = TextAlignment.Center,
                Cursor = Cursors.Hand,
                VerticalAlignment = VerticalAlignment.Center,
            };
            tb.MouseLeftButtonUp += onClick;
            tb.MouseEnter += delegate { tb.Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#1FFFFFF")); };
            tb.MouseLeave += delegate { tb.Background = Brushes.Transparent; };
            return tb;
        }

        private static TextBlock Text(string s, double size, FontWeight weight, string color, double vOff)
        {
            return new TextBlock
            {
                Text = s,
                FontSize = size,
                FontWeight = weight,
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(color)),
                Margin = new Thickness(0, vOff, 0, 0),
                TextAlignment = TextAlignment.Center,
            };
        }

        private static Button PrimaryButton(string text)
        {
            var b = new Button
            {
                Content = text,
                Height = 44,
                FontSize = 15,
                Foreground = Brushes.White,
                BorderThickness = new Thickness(0),
                Cursor = Cursors.Hand,
            };
            b.Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString(Primary));
            var bd = new FrameworkElementFactory(typeof(Border));
            bd.SetValue(Border.CornerRadiusProperty, new CornerRadius(6));
            bd.SetValue(Border.BackgroundProperty, new TemplateBindingExtension(Button.BackgroundProperty));
            var cp = new FrameworkElementFactory(typeof(ContentPresenter));
            cp.SetValue(ContentPresenter.ContentProperty, new TemplateBindingExtension(Button.ContentProperty));
            cp.SetValue(ContentPresenter.HorizontalAlignmentProperty, HorizontalAlignment.Center);
            cp.SetValue(ContentPresenter.VerticalAlignmentProperty, VerticalAlignment.Center);
            bd.AppendChild(cp);
            b.Template = new ControlTemplate(typeof(Button)) { VisualTree = bd };
            return b;
        }

        // ---------- 第 1 页：欢迎 ----------
        private StackPanel BuildWelcomePage()
        {
            var panel = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 24),   // 视觉重心略上提
            };

            // 品牌 Logo：原始尺寸 350x90 原样居中（不缩放）
            var logo = new Image
            {
                Width = 350,
                Height = 90,
                Stretch = Stretch.None,
                HorizontalAlignment = HorizontalAlignment.Center,
            };
            try
            {
                var asm = Assembly.GetExecutingAssembly();
                using (var s = asm.GetManifestResourceStream(EmbeddedLogo))
                {
                    if (s != null)
                    {
                        var bmp = new BitmapImage();
                        bmp.BeginInit();
                        bmp.StreamSource = s;
                        bmp.CacheOption = BitmapCacheOption.OnLoad;
                        bmp.EndInit();
                        bmp.Freeze();
                        logo.Source = bmp;
                    }
                }
            }
            catch { }
            panel.Children.Add(logo);

            var sub = Text("记忆 · 情感 · 自我进化的个人 AI 智能体", 12, FontWeights.Normal, TextSub, 10);
            panel.Children.Add(sub);

            _installBtn = PrimaryButton("立即安装");
            _installBtn.Width = 320;
            _installBtn.HorizontalAlignment = HorizontalAlignment.Center;
            // 初始未勾协议：禁用观感（深灰蓝）；Checked 事件切主色
            _installBtn.Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#333A55"));
            _installBtn.Margin = new Thickness(0, 28, 0, 0);
            _installBtn.Click += OnInstallClick;
            panel.Children.Add(_installBtn);

            // 链接行（GitHub / CNB / 官网，可直接点击）+ 版本行（链接在上）
            var links = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Center,
            };
            links.Children.Add(FooterLink("开源地址：", true, 0, "https://github.com/kingsa2026/Neurova"));
            links.Children.Add(FooterLink("GitHub", true, 0, "https://github.com/kingsa2026/Neurova"));
            links.Children.Add(FooterLink(" · ", false, 0, null));
            links.Children.Add(FooterLink("CNB", true, 0, "https://cnb.cool/kingsa2026/neurova"));
            links.Children.Add(FooterLink("  ｜  官网：", false, 0, null));
            links.Children.Add(FooterLink("www.neurova.top", true, 0, "https://www.neurova.top"));
            panel.Children.Add(links);

            panel.Children.Add(Text("v1.0.0", 11, FontWeights.Normal, TextSub, 6));
            return panel;
        }

        // ---------- 第 2 页：管理员账号（两次密码 + 一致性校验 + 权限警示） ----------
        private StackPanel BuildAdminPage()
        {
            // 注册区收窄：520px 玻璃背板卡片（登录页 GlassPanel 同款观感）
            var page = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center,
                Visibility = Visibility.Collapsed,
            };
            var panel = new StackPanel();   // 宽度自适应玻璃卡内容区
            // panel 暂不入树——末尾统一挂进玻璃 Border（避免双逻辑父级异常）

            panel.Children.Add(Text("创建管理员账号", 20, FontWeights.Bold, TextMain, 0));
            panel.Children.Add(Text("该账号用于登录 Neurova 智星，拥有系统最高权限", 12,
                FontWeights.Normal, TextSub, 6));

            // 横排行：白字标签居左 + 输入框居右（同一行，不换行）
            var userBox = new TextBox();   // 用户名可自定义（不设默认，提交时空值会被校验拦截）
            _adminUser = MakeAdminField(panel, "管理账号：", userBox);
            var passBox = new System.Windows.Controls.PasswordBox();
            _adminPass = MakeAdminField(panel, "设置密码：", passBox);
            var pass2Box = new System.Windows.Controls.PasswordBox();
            _adminPass2 = MakeAdminField(panel, "确认密码：", pass2Box);
            panel.Children.Add(Text("密码长度不超过 16 位，区分大小写", 11,
                FontWeights.Normal, TextSub, 6));

            // 重要提示：管理员权限警示
            var notice = new Border
            {
                Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#2A2410")),
                BorderBrush = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#F0C36D")),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(6),
                Padding = new Thickness(12, 8, 12, 8),
                Margin = new Thickness(0, 8, 0, 0),
            };
            notice.Child = new TextBlock
            {
                Text = "⚠ 重要提示：注册账号拥有管理员权限，可访问全部数据并修改系统设置，请务必妥善保管用户名与密码。",
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#E8C97A")),
            };
            panel.Children.Add(notice);

            _adminHint = new TextBlock
            {
                Text = "",
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#FF6B6B")),
                Margin = new Thickness(0, 8, 0, 0),
            };
            panel.Children.Add(_adminHint);

            var btnRow = new Grid { Margin = new Thickness(0, 8, 0, 0) };
            btnRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            btnRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var backBtn = PrimaryButton("上一步");
            backBtn.Height = 40;
            backBtn.Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#1E2740"));
            backBtn.Margin = new Thickness(0, 0, 6, 0);
            backBtn.Click += OnAdminBackClick;
            var startBtn = PrimaryButton("开始安装");
            startBtn.Height = 40;
            startBtn.FontWeight = FontWeights.Bold;
            startBtn.Margin = new Thickness(6, 0, 0, 0);
            startBtn.Click += OnStartInstallClick;
            Grid.SetColumn(backBtn, 0);
            Grid.SetColumn(startBtn, 1);
            btnRow.Children.Add(backBtn);
            btnRow.Children.Add(startBtn);
            panel.Children.Add(btnRow);

            // 玻璃背板（Border 才支持 Padding/圆角/投影；StackPanel 没有 Padding）
            var glass = new Border
            {
                // 自适应宽度 = 内容期望值，夹在 [380, 520]——文本全部 Wrap，任何语言不裁切
                MinWidth = 380,
                MaxWidth = 520,
                HorizontalAlignment = HorizontalAlignment.Center,
                Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#B3141B2E")),
                BorderBrush = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#33FFFFFF")),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(16),
                Padding = new Thickness(24, 18, 24, 18),
                Effect = new DropShadowEffect
                {
                    BlurRadius = 20, ShadowDepth = 0, Opacity = 0.4, Color = Colors.Black,
                },
            };
            glass.Child = panel;
            page.Children.Clear();
            page.Children.Add(glass);
            return page;
        }

        private T MakeAdminField<T>(StackPanel panel, string label, T input) where T : System.Windows.Controls.Control
        {
            var row = new Grid { Margin = new Thickness(0, 0, 0, 10) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(90) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            var lb = new TextBlock
            {
                Text = label,
                FontSize = 13,
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(TextMain)),
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 12, 0),
            };
            input.Height = 32;
            input.FontSize = 13;
            input.VerticalContentAlignment = VerticalAlignment.Center;
            input.Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#33FFFFFF"));
            input.Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(TextMain));
            input.BorderBrush = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#59FFFFFF"));
            input.Style = RoundedInputStyle(input.GetType());

            var tb = input as System.Windows.Controls.TextBox;
            if (tb != null) tb.CaretBrush = Brushes.White;
            var pb = input as System.Windows.Controls.PasswordBox;
            if (pb != null) pb.CaretBrush = Brushes.White;

            Grid.SetColumn(lb, 0);
            Grid.SetColumn(input, 1);
            row.Children.Add(lb);
            row.Children.Add(input);
            panel.Children.Add(row);
            return input;
        }

        private static Style RoundedInputStyle(System.Type controlType)
        {
            var bd = new FrameworkElementFactory(typeof(Border));
            bd.Name = "bd";
            bd.SetValue(Border.CornerRadiusProperty, new CornerRadius(4));
            bd.SetValue(Border.BackgroundProperty,
                new TemplateBindingExtension(System.Windows.Controls.Control.BackgroundProperty));
            bd.SetValue(Border.BorderBrushProperty,
                new TemplateBindingExtension(System.Windows.Controls.Control.BorderBrushProperty));
            bd.SetValue(Border.BorderThicknessProperty,
                new TemplateBindingExtension(System.Windows.Controls.Control.BorderThicknessProperty));
            var host = new FrameworkElementFactory(typeof(System.Windows.Controls.ScrollViewer));
            host.Name = "PART_ContentHost";
            bd.AppendChild(host);
            var tpl = new ControlTemplate(controlType) { VisualTree = bd };
            var st = new Style(controlType);
            st.Setters.Add(new Setter(System.Windows.Controls.Control.TemplateProperty, tpl));
            return st;
        }

        private static TextBlock FieldLabel(string s, double vOff)
        {
            return new TextBlock
            {
                Text = s,
                FontSize = 12,
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(TextSub)),
                Margin = new Thickness(0, vOff, 0, 4),
            };
        }

        // ---------- 第 3 页：进度 ----------
        private StackPanel BuildProgressPage()
        {
            var panel = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center,
                Visibility = Visibility.Collapsed,
            };
            _progressTitle = Text("正在安装…", 16, FontWeights.Bold, TextMain, 0);
            panel.Children.Add(_progressTitle);
            _progressBar = new ProgressBar
            {
                Height = 8, Minimum = 0, Maximum = 100, Margin = new Thickness(0, 20, 0, 0),
            };
            panel.Children.Add(_progressBar);
            _progressDetail = Text("准备中", 12, FontWeights.Normal, TextSub, 10);
            panel.Children.Add(_progressDetail);
            return panel;
        }

        // ---------- 第 4 页：完成 ----------
        private StackPanel BuildDonePage()
        {
            var panel = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center,
                Visibility = Visibility.Collapsed,
            };
            panel.Children.Add(new TextBlock
            {
                Text = "✓ 安装完成",
                FontSize = 22,
                FontWeight = FontWeights.Bold,
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#2BB673")),
                HorizontalAlignment = HorizontalAlignment.Center,
            });
            panel.Children.Add(new TextBlock
            {
                Text = "Neurova 智星 已成功安装到您的电脑",
                FontSize = 13,
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(TextMain)),
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 8, 0, 0),
            });
            _runNowCheck = new CheckBox
            {
                Content = "安装完成后立即运行 Neurova",
                IsChecked = true,
                FontSize = 13,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 24, 0, 0),
            };
            panel.Children.Add(_runNowCheck);
            var finish = PrimaryButton("立即体验");
            finish.Width = 240;
            finish.FontSize = 15;
            finish.HorizontalAlignment = HorizontalAlignment.Center;
            finish.Margin = new Thickness(0, 24, 0, 0);
            finish.Click += OnFinishClick;
            panel.Children.Add(finish);
            return panel;
        }

        // ---------- 自定义折叠区（安装位置） ----------
        private Border BuildCustomPanel()
        {
            var border = new Border
            {
                Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#0C1120")),
                Padding = new Thickness(28, 12, 28, 12),
            };
            var row = new Grid();
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(90) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(90) });
            var label = Text("安装位置：", 13, FontWeights.Normal, TextMain, 0);
            label.VerticalAlignment = VerticalAlignment.Center;
            _pathBox = new TextBox
            {
                Height = 32,
                FontSize = 13,
                VerticalContentAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 10, 0),
                Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#33FFFFFF")),
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(TextMain)),
                BorderBrush = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#59FFFFFF")),
                CaretBrush = Brushes.White,
            };
            var browse = new Button { Content = "浏览…", Width = 68, Height = 32 };
            browse.Click += OnBrowseClick;
            Grid.SetColumn(label, 0);
            Grid.SetColumn(_pathBox, 1);
            Grid.SetColumn(browse, 2);
            row.Children.Add(label);
            row.Children.Add(_pathBox);
            row.Children.Add(browse);
            border.Child = row;
            return border;
        }

        // ---------- 底部行：协议圆点 + 自定义选项 ----------
        private UIElement BuildFooterRow()
        {
            var border = new Border
            {
                Padding = new Thickness(20, 12, 20, 12),
                BorderBrush = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#14203A")),
                BorderThickness = new Thickness(0, 1, 0, 0),
            };
            var dock = new DockPanel { LastChildFill = false };
            border.Child = dock;

            var eulaRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            _eulaRadio = new RadioButton { GroupName = "eula", VerticalAlignment = VerticalAlignment.Center };
            _eulaRadio.Checked += delegate
            {
                _installBtn.IsEnabled = true;
                _installBtn.Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString(Primary));
            };
            _eulaRadio.Unchecked += delegate
            {
                _installBtn.IsEnabled = false;
                _installBtn.Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#333A55"));
            };
            eulaRow.Children.Add(_eulaRadio);
            eulaRow.Children.Add(FooterLink("阅读并同意", false, 6, null));
            eulaRow.Children.Add(FooterLink("《软件许可协议》", true, 0, TermsUrl));
            eulaRow.Children.Add(FooterLink("和", false, 4, null));
            eulaRow.Children.Add(FooterLink("《隐私政策协议》", true, 0, PrivacyUrl));
            DockPanel.SetDock(eulaRow, Dock.Left);
            dock.Children.Add(eulaRow);

            var customRow = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center,
                Cursor = Cursors.Hand,
            };
            _customArrow = new TextBlock
            {
                Text = "⌄",
                FontSize = 13,
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(TextSub)),
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 6, 0),
            };
            _customToggle = new TextBlock
            {
                Text = "自定义选项",
                FontSize = 13,
                Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(TextSub)),
                VerticalAlignment = VerticalAlignment.Center,
            };
            customRow.Children.Add(_customArrow);
            customRow.Children.Add(_customToggle);
            customRow.MouseLeftButtonUp += OnCustomToggle;
            DockPanel.SetDock(customRow, Dock.Right);
            dock.Children.Add(customRow);
            return border;
        }

        private TextBlock FooterLink(string s, bool link, double leftMargin, string url)
        {
            var tb = new TextBlock
            {
                Text = s,
                FontSize = 12.5,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(leftMargin, 0, 0, 0),
            };
            if (link)
            {
                tb.Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#8F9FFF"));
                tb.Cursor = Cursors.Hand;
                tb.MouseLeftButtonUp += delegate
                {
                    try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
                    catch { }
                };
            }
            else
            {
                tb.Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(TextSub));
            }
            return tb;
        }

        // ---------- 事件 ----------
        private void OnCustomToggle(object sender, MouseButtonEventArgs e)
        {
            bool open = _customPanel.Visibility == Visibility.Visible;
            _customPanel.Visibility = open ? Visibility.Collapsed : Visibility.Visible;
            _customArrow.Text = open ? "⌄" : "⌃";
        }

        private void OnBrowseClick(object sender, RoutedEventArgs e)
        {
            using (var dlg = new System.Windows.Forms.FolderBrowserDialog())
            {
                dlg.SelectedPath = _pathBox.Text;
                dlg.Description = "选择 Neurova 安装位置";
                if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                    _pathBox.Text = dlg.SelectedPath;
            }
        }

        private static string DefaultInstallDir()
        {
            // 复刻 NSIS perMachine 默认：历史安装目录 > D:\Program Files\Neurova > C: 兜底
            var prev = (string)Registry.GetValue(
                @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Neurova",
                "InstallLocation", null);
            if (!string.IsNullOrEmpty(prev) && Directory.Exists(prev))
                return prev;
            if (Directory.Exists(@"D:\"))
                return @"D:\Program Files\Neurova";
            return @"C:\Program Files\Neurova";
        }

        private void OnInstallClick(object sender, RoutedEventArgs e)
        {
            if (_eulaRadio.IsChecked != true) return;
            _installTarget = _pathBox.Text.Trim().TrimEnd('\\');

            // 升级安装：跳过管理员注册页，直接开始（凭据沿用既有安装）
            if (_isUpgrade)
            {
                StartInstall(_installTarget, null, null);
                return;
            }
            _pageWelcome.Visibility = Visibility.Collapsed;
            _pageAdmin.Visibility = Visibility.Visible;
            _adminHint.Text = "";
        }

        private string ValidateAdminInput()
        {
            // 对齐 NSIS ValidateAdminUsername：用户名 1..32 位，
            // 禁 " \t ":/\\<>|?*%$"；密码非空 + 两次大小写敏感一致
            string user = _adminUser.Text.Trim();
            string p1 = _adminPass.Password;
            string p2 = _adminPass2.Password;
            if (user.Length < 1 || user.Length > 32)
                return "用户名长度须为 1-32 个字符";
            foreach (char c in " \t\":/\\<>|?*%$")
            {
                if (user.IndexOf(c) >= 0)
                    return "用户名含非法字符（空格 : / \\ < > | ? * % $ \"）";
            }
            if (p1.Length == 0)
                return "请设置密码";
            if (p1.Length > 16)
                return "密码长度须为 16 位以内";
            if (string.CompareOrdinal(p1, p2) != 0)
                return "两次输入的密码不一致，请重新确认";
            return null;
        }

        private void OnAdminBackClick(object sender, RoutedEventArgs e)
        {
            _adminHint.Text = "";
            _pageAdmin.Visibility = Visibility.Collapsed;
            _pageWelcome.Visibility = Visibility.Visible;
        }

        private void OnStartInstallClick(object sender, RoutedEventArgs e)
        {
            string err = ValidateAdminInput();
            if (err != null)
            {
                _adminHint.Text = err;
                return;
            }
            _adminHint.Text = "";
            StartInstall(_installTarget, _adminUser.Text.Trim(), _adminPass.Password);
        }

        private void StartInstall(string targetDir, string adminUser, string adminPass)
        {
            _pageAdmin.Visibility = Visibility.Collapsed;
            _pageProgress.Visibility = Visibility.Visible;
            _customPanel.Visibility = Visibility.Collapsed;
            _progressTitle.Text = "正在准备…";
            _progressDetail.Text = "";

            string kernel = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, NsisKernel);
            if (!File.Exists(kernel))
            {
                kernel = Path.Combine(Path.GetTempPath(), "NeurovaSetup", NsisKernel);
            }

            ThreadPool.QueueUserWorkItem(delegate
            {
                // 阶段一：内核就绪（侧车存在 → 跳过解压；否则解压内嵌资源 0-15%）
                string effectiveKernel = kernel;
                if (!File.Exists(effectiveKernel))
                {
                    string err = ExtractEmbeddedKernel(effectiveKernel, delegate (int pct)
                    {
                        Dispatcher.Invoke(delegate
                        {
                            _progressBar.Value = pct * 15 / 100;
                            _progressDetail.Text = "正在准备安装程序 " + pct + "%";
                        });
                    });
                    if (err != null)
                    {
                        Dispatcher.Invoke(delegate { InstallFailed("准备安装程序失败：" + err); });
                        return;
                    }
                    _kernelExtracted = true;
                }

                Dispatcher.Invoke(delegate
                {
                    _progressTitle.Text = "正在安装…";
                    _progressBar.Value = 15;
                });

                // 阶段二：NSIS /S 静默安装（15-95% 按目录增长映射）
                var psi = new ProcessStartInfo
                {
                    FileName = effectiveKernel,
                    Arguments = "/S /D=" + targetDir,
                    UseShellExecute = true,
                    Verb = "runas",
                };
                try
                {
                    _installProc = Process.Start(psi);
                }
                catch (Exception ex)
                {
                    Dispatcher.Invoke(delegate { InstallFailed("无法启动安装内核：" + ex.Message); });
                    return;
                }

                var di = new DirectoryInfo(targetDir);
                while (true)
                {
                    Thread.Sleep(500);
                    var proc = _installProc;
                    if (proc == null) return;
                    proc.Refresh();
                    if (proc.HasExited)
                    {
                        int exit = proc.ExitCode;
                        if (exit != 0)
                        {
                            Dispatcher.Invoke(delegate { FinishInstall(exit, targetDir, adminUser, adminPass); });
                            return;
                        }
                        // 阶段三：系统组件（缺 VC++ 运行库 → 自动下载安装，不阻断）
                        Dispatcher.Invoke(delegate
                        {
                            _progressTitle.Text = "正在配置系统组件…";
                            _progressDetail.Text = "检测运行库环境";
                        });
                        string vcErr = EnsureVcRedist();
                        Dispatcher.Invoke(delegate { FinishInstall(0, targetDir, adminUser, adminPass, vcErr); });
                        return;
                    }
                    long bytes = DirSize(di);
                    int pct = (int)Math.Min(95, 15 + bytes * 80 / 1900000000L);
                    Dispatcher.Invoke(delegate
                    {
                        _progressBar.Value = pct;
                        _progressDetail.Text = "已写入 " + (bytes / 1024 / 1024) + " MB";
                    });
                }
            });
        }

        private string ExtractEmbeddedKernel(string destPath, Action<int> onProgress)
        {
            try
            {
                var asm = Assembly.GetExecutingAssembly();
                using (var src = asm.GetManifestResourceStream(EmbeddedKernel))
                {
                    if (src == null) return "安装内核未嵌入（构建时缺少 NSIS 产物）";
                    long total = src.Length;
                    Directory.CreateDirectory(Path.GetDirectoryName(destPath));
                    using (var dst = new FileStream(destPath, FileMode.Create, FileAccess.Write))
                    {
                        var buf = new byte[1024 * 1024];
                        long written = 0;
                        int n;
                        while ((n = src.Read(buf, 0, buf.Length)) > 0)
                        {
                            dst.Write(buf, 0, n);
                            written += n;
                            if (onProgress != null && total > 0)
                                onProgress((int)(written * 100 / total));
                        }
                    }
                }
                return null;
            }
            catch (Exception ex)
            {
                return ex.Message;
            }
        }

        private void InstallFailed(string msg)
        {
            _progressTitle.Text = "安装中断";
            _progressDetail.Text = msg;
            _pageProgress.Visibility = Visibility.Collapsed;
            _pageWelcome.Visibility = Visibility.Visible;
        }

        private void FinishInstall(int exit, string targetDir, string adminUser, string adminPass)
        {
            FinishInstall(exit, targetDir, adminUser, adminPass, null);
        }

        private void FinishInstall(int exit, string targetDir, string adminUser, string adminPass, string vcErr)
        {
            if (exit == 0)
            {
                _progressBar.Value = 100;
                WriteBootstrapAdminIni(targetDir, adminUser, adminPass);
                _pageProgress.Visibility = Visibility.Collapsed;
                _pageDone.Visibility = Visibility.Visible;
                if (vcErr != null)
                {
                    // VC++ 自动安装失败：不阻断安装完成，明示影响与补救
                    _progressDetail.Text = "系统组件(VC++运行库)安装未完成：" + vcErr
                        + "。后端部分功能（AI 计算）可能受限，可手动安装后重试。";
                }
            }
            else
            {
                InstallFailed("安装内核退出码 " + exit + "，可重新运行安装程序。");
            }
            if (_kernelExtracted)
            {
                try
                {
                    var tmp = Path.Combine(Path.GetTempPath(), "NeurovaSetup", NsisKernel);
                    if (File.Exists(tmp)) File.Delete(tmp);
                }
                catch { }
            }
        }

        // 管理员凭据 → <安装目录>\backend\data\bootstrap_admin.ini
        // 与 NSIS PageAdminAccount 同通道：后端首启消费即删（fail-open）。
        // UTF-8 BOM（后端 _read_ini_text 多编码尝试，utf-8-sig 优先）。
        private void WriteBootstrapAdminIni(string targetDir, string adminUser, string adminPass)
        {
            if (string.IsNullOrEmpty(adminUser) || string.IsNullOrEmpty(adminPass)) return;
            try
            {
                string dir = Path.Combine(targetDir, "backend", "data");
                Directory.CreateDirectory(dir);
                string path = Path.Combine(dir, "bootstrap_admin.ini");
                string content = "[bootstrap]\r\nusername=" + adminUser
                    + "\r\npassword=" + adminPass + "\r\n";
                File.WriteAllText(path, content, new System.Text.UTF8Encoding(true));
            }
            catch
            {
                // 写入失败不阻断安装——首启管理员由应用内向导兜底
                try
                {
                    _progressDetail.Text = "管理员凭据文件写入失败，首次启动时请在应用内设置管理员";
                }
                catch { }
            }
        }

        private static long DirSize(DirectoryInfo dir)
        {
            long total = 0;
            try
            {
                foreach (var f in dir.EnumerateFiles("*", SearchOption.AllDirectories))
                {
                    try { total += f.Length; } catch { }
                }
            }
            catch { }
            return total;
        }

        private void OnFinishClick(object sender, RoutedEventArgs e)
        {
            if (_runNowCheck.IsChecked == true)
            {
                var exe = Path.Combine(_pathBox.Text, "Neurova.exe");
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
