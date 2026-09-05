// signtool 透传包装器：记录每次调用参数与输出，失败自动重试。
// 背景：tauri 批量签名几十个 DLL 时，digicert 时间戳服务器从国内网络
// 间歇可达，单次瞬时失败即废整轮 tauri build（0x80093102 无输出黑盒）。
// 用法：TAURI_WINDOWS_SIGNTOOL_PATH 指向本包装器 exe。
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

static class Wrapper
{
    static readonly string RealSigntool =
        @"C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe";
    static readonly string LogFile =
        Path.Combine(Path.GetTempPath(), "neurova-signtool-wrap.log");

    static int Main(string[] args)
    {
        var sb = new StringBuilder();
        sb.AppendLine("==== " + DateTime.Now.ToString("HH:mm:ss.fff") + " ====");
        sb.AppendLine("ARGS: " + string.Join(" ", args));

        for (int attempt = 1; attempt <= 3; attempt++)
        {
            var psi = new ProcessStartInfo
            {
                FileName = RealSigntool,
                Arguments = QuoteArgs(args),
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            using (var p = Process.Start(psi))
            {
                string so = p.StandardOutput.ReadToEnd();
                string se = p.StandardError.ReadToEnd();
                p.WaitForExit();
                sb.AppendLine("[try " + attempt + "] exit=" + p.ExitCode);
                if (so.Length > 0) sb.AppendLine("STDOUT: " + so.Trim());
                if (se.Length > 0) sb.AppendLine("STDERR: " + se.Trim());
                if (p.ExitCode == 0)
                {
                    sb.AppendLine("[ok]");
                    Flush(sb);
                    return 0;
                }
                if (attempt < 3) Thread.Sleep(3000);
            }
        }
        sb.AppendLine("[fail] 3 attempts exhausted");
        Flush(sb);
        return 1;
    }

    static string QuoteArgs(string[] args)
    {
        var sb = new StringBuilder();
        foreach (var a in args)
        {
            if (sb.Length > 0) sb.Append(' ');
            // 含空格的参数加引号（signtool 参数多为无空格开关与单文件路径）
            if (a.IndexOf(' ') >= 0 && a[0] != '"') sb.Append('"').Append(a).Append('"');
            else sb.Append(a);
        }
        return sb.ToString();
    }

    static void Flush(StringBuilder sb)
    {
        try { File.AppendAllText(LogFile, sb.ToString()); } catch { }
    }
}
