// SPDX-License-Identifier: AGPL-3.0-or-later
// MDEditor installer (WinForms). Compiled at packaging time by the system
// csc.exe (Windows built-in .NET Framework compiler). No third-party tools.
//
// Embedded resources (added by _build_installer.py):
//   payload.zip  - dist checklist minimum set (UTF-8 entry names, python zipfile)
//   ver.txt      - installer/app version string
//
// Usage:  MDEditor-Setup-vX.Y.Z.exe            (installer GUI)
//         MDEditor-Setup-vX.Y.Z.exe --smoke    (headless self-check, writes
//                                               %TEMP%\md_setup_smoke_report.txt)
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Windows.Forms;
using Microsoft.Win32;

namespace MDEditorSetup
{
    static class Setup
    {
        internal const string ResZip = "payload.zip";
        internal const string ResVer = "ver.txt";
        internal static readonly string Version = ReadVersion();

        [STAThread]
        static void Main(string[] args)
        {
            if (args != null && args.Any(a => string.Equals(a, "--smoke", StringComparison.OrdinalIgnoreCase)))
            {
                RunSmoke();
                return;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupForm());
        }

        static Stream Res(string name)
        {
            var s = typeof(Setup).Assembly.GetManifestResourceStream(name);
            if (s == null) throw new FileNotFoundException("missing resource: " + name);
            return s;
        }

        static string ReadVersion()
        {
            using (var s = Res(ResVer))
            using (var r = new StreamReader(s))
                return r.ReadToEnd().Trim();
        }

        internal static ZipArchive OpenPayload()
        {
            // copy to memory so the zip stays usable after the resource stream is disposed
            using (var s = Res(ResZip))
            {
                var ms = new MemoryStream();
                s.CopyTo(ms);
                ms.Position = 0;
                return new ZipArchive(ms, ZipArchiveMode.Read);
            }
        }

        static void ExtractEntry(ZipArchiveEntry entry, string dst)
        {
            var full = Path.GetFullPath(dst);
            if (!full.StartsWith(_extractRoot, StringComparison.OrdinalIgnoreCase))
                throw new IOException("zip-slip blocked: " + entry.FullName);
            var dir = Path.GetDirectoryName(full);
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            if (entry.Name != "") entry.ExtractToFile(full, true);
        }

        static string _extractRoot = "";

        internal static void ExtractTo(string target, Action<int, int> progress)
        {
            _extractRoot = Path.GetFullPath(target);
            using (var zip = OpenPayload())
            {
                var entries = zip.Entries.Where(e => e.FullName != "" && !e.FullName.EndsWith("/")).ToList();
                int total = entries.Count, done = 0;
                foreach (var e in entries)
                {
                    ExtractEntry(e, Path.Combine(target, e.FullName.Replace('/', Path.DirectorySeparatorChar)));
                    done++;
                    if (progress != null && (done % 25 == 0 || done == total))
                        progress(done, total);
                }
            }
        }

        static long DirSize(string dir)
        {
            long sum = 0;
            foreach (var f in Directory.GetFiles(dir, "*", SearchOption.AllDirectories))
                sum += new FileInfo(f).Length;
            return sum;
        }

        internal static bool WebView2Present()
        {
            string[] keys = {
                @"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
                @"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
            };
            foreach (var root in new[] { Registry.LocalMachine, Registry.CurrentUser })
                foreach (var k in keys)
                    try { using (var rk = root.OpenSubKey(k)) if (rk != null) return true; } catch { }
            foreach (var p in new[] {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), @"Microsoft\EdgeWebView\Application"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"Microsoft\EdgeWebView\Application") })
                try
                {
                    if (Directory.Exists(p) && Directory.GetDirectories(p)
                        .Any(d => { var n = Path.GetFileName(d); return n.Length > 0 && char.IsDigit(n[0]); }))
                        return true;
                } catch { }
            return false;
        }

        static Process RunHidden(string exe, string args, string cwd)
        {
            var psi = new ProcessStartInfo(exe, args)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = string.IsNullOrEmpty(cwd) ? null : cwd
            };
            var p = Process.Start(psi);
            p.WaitForExit(300000);
            return p;
        }

        static void WriteArpExtras(string target, Action<string> log)
        {
            // install.cmd owns the ARP entry (single source). Here we only
            // supplement the fields only the installer knows: version + size.
            try
            {
                using (var k = Registry.CurrentUser.OpenSubKey(
                    @"Software\Microsoft\Windows\CurrentVersion\Uninstall\MDEditor", true))
                {
                    if (k == null)
                    {
                        log("[!] 卸载条目缺失（install.cmd 未完成第 5 步登记）");
                        return;
                    }
                    k.SetValue("DisplayVersion", Version);
                    k.SetValue("EstimatedSize", (int)Math.Min(DirSize(target) / 1024, (long)int.MaxValue), RegistryValueKind.DWord);
                    log("卸载条目已就绪：设置 → 应用 → \"MDEditor (Markdown Editor)\"。");
                }
            }
            catch (Exception ex) { log("[!] 卸载条目补充失败: " + ex.Message); }
        }

        internal static void Install(string target, Action<string> log, Action<int> pct, Action done, Action<string> fail)
        {
            var bw = new BackgroundWorker { WorkerReportsProgress = true };
            bw.ProgressChanged += (s, e) => pct(e.ProgressPercentage);
            bw.RunWorkerCompleted += (s, e) =>
            {
                if (e.Error != null) fail(e.Error.Message);
                else done();
            };
            bw.DoWork += (s, e) =>
            {
                if (File.Exists(Path.Combine(target, "md_server.py")))
                {
                    log("[升级] 检测到已有安装，先停止运行中的服务...");
                    var stop = Path.Combine(target, "md_stop.cmd");
                    if (File.Exists(stop)) RunHidden("cmd.exe", "/c \"" + stop + "\"", target);
                    else RunHidden("cmd.exe", "/c \"" + Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "md_stop.cmd") + "\"", target);
                    System.Threading.Thread.Sleep(800);
                }
                log("复制文件到 " + target + " ...");
                ExtractTo(target, (d, t) => { bw.ReportProgress(d * 100 / t); log("  " + d + "/" + t); });
                log("系统集成（右键菜单 / 图标 / 快捷方式 / EXE 编译 / 卸载条目登记）...");
                var p = RunHidden("cmd.exe", "/c install.cmd nopause", target);
                log(p.ExitCode == 0 ? "install.cmd 执行成功。" : "[!] install.cmd 退出码 " + p.ExitCode + "（可稍后在安装目录手动重跑）");
                WriteArpExtras(target, log);
                log("");
                log("安装完成：" + target);
                log("右键 .md 文件可用 MDEditor 打开。");
            };
            bw.RunWorkerAsync();
        }

        static void RunSmoke()
        {
            var tmp = Path.Combine(Path.GetTempPath(), "md_setup_smoke");
            try { if (Directory.Exists(tmp)) Directory.Delete(tmp, true); } catch { }
            var lines = new List<string>();
            ExtractTo(tmp, null);
            string docs = Path.Combine(tmp, "docs");
            string guide = Path.Combine(docs, "MDEditor 使用指南.md");
            string lic = Path.Combine(docs, "版权与开源组件声明.md");
            string dll = Path.Combine(tmp, @"python\Lib\site-packages\pythonnet\runtime\Python.Runtime.dll");
            string fonts = Path.Combine(tmp, @"katex\fonts");
            string uico = Path.Combine(tmp, "uninstall-md.ico");
            string ucs = Path.Combine(tmp, "UninstallMDEditor.cs");
            string mjs = Path.Combine(tmp, @"mermaid\mermaid.min.js");
            string vjs = Path.Combine(tmp, @"viz\viz-standalone.js");
            string wjs = Path.Combine(tmp, @"wavedrom\wavedrom.min.js");
            string wsk = Path.Combine(tmp, @"wavedrom\skins\default.js");
            string wskd = Path.Combine(tmp, @"wavedrom\skins\dark.js");
            string gejs = Path.Combine(tmp, @"vega\vega-embed.min.js");
            lines.Add("total_files=" + Directory.GetFiles(tmp, "*", SearchOption.AllDirectories).Length);
            lines.Add("guide_md_exists=" + (File.Exists(guide) ? 1 : 0));
            lines.Add("license_doc_exists=" + (File.Exists(lic) ? 1 : 0));
            lines.Add("uninstall_icon_exists=" + (File.Exists(uico) ? 1 : 0));
            lines.Add("uninstaller_cs_exists=" + (File.Exists(ucs) ? 1 : 0));
            lines.Add("docs_listing=" + string.Join(";", Directory.GetFileSystemEntries(docs).Select(Path.GetFileName)));
            lines.Add("pythonnet_dll_size=" + (File.Exists(dll) ? new FileInfo(dll).Length : 0));
            lines.Add("katex_fonts_count=" + (Directory.Exists(fonts) ? Directory.GetFiles(fonts).Length : 0));
            lines.Add("pythonw_exists=" + (File.Exists(Path.Combine(tmp, @"python\pythonw.exe")) ? 1 : 0));
            lines.Add("webview2=" + (WebView2Present() ? 1 : 0));
            lines.Add("mermaid_vendor_size=" + (File.Exists(mjs) ? new FileInfo(mjs).Length : 0));
            lines.Add("viz_vendor_size=" + (File.Exists(vjs) ? new FileInfo(vjs).Length : 0));
            lines.Add("wavedrom_vendor_size=" + (File.Exists(wjs) ? new FileInfo(wjs).Length : 0));
            lines.Add("wavedrom_skin_size=" + (File.Exists(wsk) ? new FileInfo(wsk).Length : 0));
            lines.Add("wavedrom_skin_dark_size=" + (File.Exists(wskd) ? new FileInfo(wskd).Length : 0));
            lines.Add("vega_embed_vendor_size=" + (File.Exists(gejs) ? new FileInfo(gejs).Length : 0));
            lines.Add("version=" + Version);
            File.WriteAllLines(Path.Combine(Path.GetTempPath(), "md_setup_smoke_report.txt"), lines);
            try { Directory.Delete(tmp, true); } catch { }
        }
    }

    class SetupForm : Form
    {
        readonly TextBox _txtDir = new TextBox();
        readonly TextBox _txtLog = new TextBox();
        readonly ProgressBar _prog = new ProgressBar();
        readonly Button _btnInstall = new Button();
        readonly Button _btnRun = new Button();
        readonly Button _btnBrowse = new Button();
        readonly Label _lblWv2 = new Label();
        string _target;

        public SetupForm()
        {
            Text = "MDEditor v" + Setup.Version + " 安装程序";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            ClientSize = new Size(620, 480);

            var lblTitle = new Label
            {
                Text = "MDEditor v" + Setup.Version + " 安装程序",
                Font = new Font(FontFamily.GenericSansSerif, 14, FontStyle.Bold),
                Location = new Point(20, 15),
                Size = new Size(580, 30)
            };
            bool wv2 = Setup.WebView2Present();
            _lblWv2.Text = wv2
                ? "[OK] 检测到 WebView2 运行时 —— 内嵌窗口可用（系统内核，不捆绑）"
                : "[!] 未检测到 WebView2 运行时 —— 将以浏览器模式打开（其余功能不受影响）";
            _lblWv2.ForeColor = wv2 ? Color.ForestGreen : Color.DarkOrange;
            _lblWv2.Location = new Point(22, 52);
            _lblWv2.Size = new Size(580, 22);

            var lblDir = new Label { Text = "安装目录：", Location = new Point(22, 88), Size = new Size(76, 22) };
            _txtDir.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MDEditor");
            _txtDir.Location = new Point(100, 85);
            _txtDir.Size = new Size(400, 23);

            _btnBrowse.Text = "浏览...";
            _btnBrowse.Location = new Point(510, 83);
            _btnBrowse.Size = new Size(90, 26);
            _btnBrowse.Click += (s, e) =>
            {
                using (var d = new FolderBrowserDialog { Description = "选择 MDEditor 安装目录", SelectedPath = _txtDir.Text })
                    if (d.ShowDialog(this) == DialogResult.OK) _txtDir.Text = d.SelectedPath;
            };

            _btnInstall.Text = "开始安装";
            _btnInstall.Location = new Point(20, 120);
            _btnInstall.Size = new Size(120, 30);
            _btnInstall.Click += (s, e) => StartInstall();

            _prog.Location = new Point(155, 124);
            _prog.Size = new Size(445, 22);

            _txtLog.Multiline = true;
            _txtLog.ReadOnly = true;
            _txtLog.ScrollBars = ScrollBars.Vertical;
            _txtLog.Font = new Font(FontFamily.GenericMonospace, 9);
            _txtLog.Location = new Point(20, 162);
            _txtLog.Size = new Size(580, 250);

            _btnRun.Text = "立即运行";
            _btnRun.Enabled = false;
            _btnRun.Location = new Point(372, 428);
            _btnRun.Size = new Size(112, 30);
            _btnRun.Click += (s, e) =>
            {
                var pyw = Path.Combine(_target, "python", "pythonw.exe");
                var entry = Path.Combine(_target, "md_launch.pyw");
                Process.Start(new ProcessStartInfo(pyw, "\"" + entry + "\"") { WorkingDirectory = _target, UseShellExecute = false });
                Close();
            };

            var btnExit = new Button { Text = "退出", Location = new Point(494, 428), Size = new Size(106, 30) };
            btnExit.Click += (s, e) => Close();

            Controls.AddRange(new Control[] { lblTitle, _lblWv2, lblDir, _txtDir, _btnBrowse, _btnInstall, _prog, _txtLog, _btnRun, btnExit });
            AcceptButton = _btnInstall;
        }

        void Log(string msg)
        {
            if (_txtLog.InvokeRequired) { _txtLog.BeginInvoke((Action)(() => Log(msg))); return; }
            _txtLog.AppendText(msg + Environment.NewLine);
        }

        void StartInstall()
        {
            var target = _txtDir.Text.Trim();
            if (target.Length == 0) { MessageBox.Show("请先选择安装目录。"); return; }
            if (string.Equals(Path.GetFullPath(target), Path.GetFullPath(Application.StartupPath), StringComparison.OrdinalIgnoreCase))
            { MessageBox.Show("安装目录不能与安装包自身所在目录相同。"); return; }
            _btnInstall.Enabled = false; _btnBrowse.Enabled = false; _txtDir.Enabled = false;
            _prog.Value = 0;
            Setup.Install(target,
                log => Log(log),
                pct => { if (_prog.InvokeRequired) _prog.BeginInvoke((Action)(() => _prog.Value = pct)); else _prog.Value = pct; },
                () =>
                {
                    if (_prog.InvokeRequired) _prog.BeginInvoke((Action)(() => _prog.Value = _prog.Maximum));
                    else _prog.Value = _prog.Maximum;
                    _target = target;
                    _btnRun.Enabled = true;
                    _btnInstall.Enabled = true; _btnBrowse.Enabled = true; _txtDir.Enabled = true;
                },
                err =>
                {
                    Log("[错误] " + err);
                    MessageBox.Show("安装失败：" + err);
                    _btnInstall.Enabled = true; _btnBrowse.Enabled = true; _txtDir.Enabled = true;
                });
        }
    }
}
