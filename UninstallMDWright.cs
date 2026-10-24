// SPDX-License-Identifier: AGPL-3.0-or-later
// MDWright uninstaller GUI. Compiled at install time by the system csc.exe
// (Windows built-in .NET Framework compiler). No third-party tools.
//
// Safety model (root-cause of the 2026-10-19 workspace-loss incident):
//   - uninstall.cmd NEVER deletes program files; it only clears registry
//     integration, shortcuts and the ARP entry. It is safe to run anywhere.
//   - File deletion happens ONLY here, opt-in via checkbox, with a second
//     explicit confirmation, and only after this GUI process exits.
//
// Compiled with: csc /target:winexe /win32icon:uninstall-mdwright.ico UninstallMDWright.cs
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;

namespace MDWrightUninstall
{
    static class Entry
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new UninstallForm());
        }
    }

    class UninstallForm : Form
    {
        readonly Label _lblDir = new Label();
        readonly CheckBox _chkFiles = new CheckBox();
        readonly TextBox _txtLog = new TextBox();
        readonly Button _btnGo = new Button();

        public UninstallForm()
        {
            string dir = AppDomain.CurrentDomain.BaseDirectory;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            Text = "卸载 MDWright";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            ClientSize = new Size(520, 330);

            var lblTitle = new Label
            {
                Text = "卸载 MDWright",
                Font = new Font(FontFamily.GenericSansSerif, 14, FontStyle.Bold),
                Location = new Point(20, 15),
                Size = new Size(480, 30)
            };

            _lblDir.Text = "安装目录：" + dir;
            _lblDir.ForeColor = Color.DimGray;
            _lblDir.Location = new Point(22, 52);
            _lblDir.Size = new Size(480, 22);

            var lblDesc = new Label
            {
                Text = "卸载将清除：.md/.smd 右键菜单与文件关联、桌面/开始菜单快捷方式、" +
                       "「设置 → 应用」卸载条目，并停止运行中的服务。\n" +
                       "程序文件默认保留，可随时重新安装或继续绿色使用。",
                Location = new Point(22, 82),
                Size = new Size(480, 56)
            };

            _chkFiles.Text = "同时删除程序文件（不可恢复）";
            _chkFiles.Location = new Point(22, 146);
            _chkFiles.Size = new Size(480, 22);

            _txtLog.Multiline = true;
            _txtLog.ReadOnly = true;
            _txtLog.ScrollBars = ScrollBars.Vertical;
            _txtLog.Font = new Font(FontFamily.GenericMonospace, 9);
            _txtLog.Location = new Point(20, 176);
            _txtLog.Size = new Size(480, 100);

            _btnGo.Text = "卸载";
            _btnGo.Location = new Point(268, 288);
            _btnGo.Size = new Size(112, 30);
            _btnGo.Click += (s, e) => Go(dir);

            var btnCancel = new Button { Text = "取消", Location = new Point(388, 288), Size = new Size(112, 30) };
            btnCancel.Click += (s, e) => Close();

            Controls.AddRange(new Control[] { lblTitle, _lblDir, lblDesc, _chkFiles, _txtLog, _btnGo, btnCancel });
            AcceptButton = _btnGo;
            CancelButton = btnCancel;
        }

        void Log(string msg)
        {
            if (_txtLog.InvokeRequired) { _txtLog.BeginInvoke((Action)(() => Log(msg))); return; }
            _txtLog.AppendText(msg + Environment.NewLine);
        }

        void Go(string dir)
        {
            if (MessageBox.Show("开始卸载 MDWright？（程序文件默认保留）",
                "确认", MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK)
                return;
            _btnGo.Enabled = false;
            _chkFiles.Enabled = false;
            try
            {
                Log("清除注册表集成 / 快捷方式 / 卸载条目 ...");
                var cmd = Path.Combine(dir, "uninstall.cmd");
                var psi = new ProcessStartInfo("cmd.exe", "/c \"" + cmd + "\" nopause")
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WorkingDirectory = Path.GetTempPath()
                };
                var p = Process.Start(psi);
                if (!p.WaitForExit(120000)) Log("[!] uninstall.cmd 超时");
                else Log("uninstall.cmd 完成（退出码 " + p.ExitCode + "）。");
                Log("程序文件未删除：" + dir);
            }
            catch (Exception ex)
            {
                Log("[!] " + ex.Message);
            }

            if (_chkFiles.Checked)
            {
                var ask = MessageBox.Show(
                    "将永久删除程序目录及其全部文件：\n\n" + dir +
                    "\n\n此操作不可恢复，确认删除？",
                    "二次确认", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning);
                if (ask == DialogResult.OK)
                {
                    SpawnSelfDelete(dir);
                    Application.Exit();
                    return;
                }
            }
            Log("卸载完成。");
            _btnGo.Text = "完成";
            _btnGo.Enabled = true;
            _btnGo.Click += (s, e) => Close();
        }

        // Spawn a detached cleanup script that waits for THIS process to exit
        // (directory stays locked while the GUI exe is running), then removes
        // the program directory. Capped at 20 retries to never loop forever.
        void SpawnSelfDelete(string dir)
        {
            var script = "@echo off\r\n" +
                         "set /a n=0\r\n" +
                         ":retry\r\n" +
                         "rd /s /q \"" + dir + "\" >nul 2>&1\r\n" +
                         "if not exist \"" + dir + "\" goto done\r\n" +
                         "set /a n=n+1\r\n" +
                         "if %n% geq 20 goto done\r\n" +
                         "ping -n 2 127.0.0.1 >nul\r\n" +
                         "goto retry\r\n" +
                         ":done\r\n" +
                         "del \"%~f0\" >nul 2>&1\r\n";
            var tmp = Path.Combine(Path.GetTempPath(), "md_uninstall_cleanup.cmd");
            File.WriteAllText(tmp, script, Encoding.ASCII);
            Process.Start(new ProcessStartInfo("cmd.exe", "/c \"" + tmp + "\"")
            {
                UseShellExecute = false,
                CreateNoWindow = true
            });
        }
    }
}
