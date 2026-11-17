// MangoServer-Setup.exe — File cai dat duy nhat cua Mango Server 1.2.1.
// Cach dung tren may moi: chi can copy 1 file MangoServer-Setup-1.2.1.exe
// sang may do, nhap cong + thu muc data + mat khau quan tri, bam "Cai dat".
// Server tu chay lai sau khi may khoi dong (Scheduled Task MangoServer,
// SYSTEM, luc khoi dong) ma KHONG can ai dang nhap.
//
// Co che: 2 goi zip duoc nhung san trong file exe duoi dang resource:
//   - MangoMCPFull.zip : goi MangoMCP Full (chi lay thu muc python lam
//     runtime, KHONG cai MangoMCP).
//   - MangoServer.zip  : goi server 1.2.1 (run_server.py + init_server.py
//     + start_server.bat + mangoserver/ + install_server.ps1 +
//     uninstall_server.ps1 + set_admin.py).
// Khi chay, app giai nen goi ra thu muc tam, roi chay install_server.ps1:
// copy code vao C:\MangoMCPServer\, dat mat khau quan tri (chi luu hash),
// tao token Agent (hien 1 lan), tao Scheduled Task MangoServer (SYSTEM,
// AtStartup), dang ky Windows Uninstall, chay Server lan dau + kiem tra
// /health. Sau khi xong, thu muc tam duoc don. File exe nay khong chua
// mat khau hay token that.
//
// Che do silent (de cai tu dong / kiem thu tren may test):
//   MangoServer-Setup-1.2.1.exe /SILENT /PORT:8443
//     /DATADIR:C:\MangoMCPServer\data /ADMINPASSWORD:<mat-khau>
// Neu thieu /ADMINPASSWORD o che do silent thi sinh mat khau ngau nhien
// va ghi vao %TEMP%\MangoServer-install-creds.txt (cung voi token Agent
// neu co) — doc xong nho xoa file do.
// Luu y: file exe CHI build duoc tren Windows (csc.exe + goi MangoMCP
// Full chi co tren may Windows).
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

namespace MangoServerSetup
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            if (IsSilent(args))
            {
                int code = SilentInstall.Run(args);
                Environment.Exit(code);
                return;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupForm());
        }

        private static bool IsSilent(string[] args)
        {
            foreach (string a in args)
            {
                if (a != null && (a.Equals("/SILENT", StringComparison.OrdinalIgnoreCase)
                    || a.Equals("-SILENT", StringComparison.OrdinalIgnoreCase)
                    || a.Equals("/S", StringComparison.OrdinalIgnoreCase)))
                    return true;
            }
            return false;
        }
    }

    // Log debug cho che do silent: ghi ra
    // %TEMP%\MangoServer-silent-debug.txt (mo file nay khi silent thoat
    // ma loi ma khong de lai log cai dat). CHI ghi tham so da parse,
    // duong dan, ma thoat, loi — KHONG BAO GIO ghi mat khau quan tri hay
    // token Agent (mat khau chi di qua bien moi truong cua tien trinh con,
    // khong nam tren dong lenh). Ghi log khong bao gio nem loi ra ngoai.
    static class SilentDebug
    {
        public static string DebugPath()
        {
            return Path.Combine(Path.GetTempPath(), "MangoServer-silent-debug.txt");
        }

        public static void Log(string msg)
        {
            try
            {
                string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " [setup] " + msg + Environment.NewLine;
                File.AppendAllText(DebugPath(), line, Encoding.UTF8);
            }
            catch { }
        }
    }

    // Cai dat khong giao dien: dung chung luong giai nen + goi ps1 nhu GUI.
    static class SilentInstall
    {
        public static int Run(string[] args)
        {
            string port = "8443";
            string dataDir = @"C:\MangoMCPServer\data";
            string installDir = @"C:\MangoMCPServer";
            string password = "";
            foreach (string raw in args)
            {
                string a = raw ?? "";
                if (a.StartsWith("/PORT:", StringComparison.OrdinalIgnoreCase)) port = a.Substring(6);
                else if (a.StartsWith("/DATADIR:", StringComparison.OrdinalIgnoreCase)) dataDir = a.Substring(9);
                else if (a.StartsWith("/INSTALLDIR:", StringComparison.OrdinalIgnoreCase)) installDir = a.Substring(12);
                else if (a.StartsWith("/ADMINPASSWORD:", StringComparison.OrdinalIgnoreCase)) password = a.Substring(15);
                else if (a.StartsWith("/PASSWORD:", StringComparison.OrdinalIgnoreCase)) password = a.Substring(10);
            }
            bool generated = false;
            if (string.IsNullOrEmpty(password))
            {
                password = InstallerCore.RandomPassword(16);
                generated = true;
            }
            // Debug silent (17/11/2026): ban 1.2.0 chay silent thoat ma 1
            // rat nhanh, khong cai gi, khong co log — ghi tung buoc ra
            // %TEMP%\MangoServer-silent-debug.txt de biet dung o dau.
            // (Chi ghi "co/khong co mat khau", KHONG ghi gia tri mat khau.)
            SilentDebug.Log("Bat dau silent install. port=" + port + ", dataDir=" + dataDir + ", installDir=" + installDir + ", password=" + (generated ? "sinh-ngau-nhien" : "da-nhap") + ", exe=" + Assembly.GetExecutingAssembly().Location);
            string tempRoot = "";
            try
            {
                tempRoot = Path.Combine(Path.GetTempPath(), "MangoServer-Setup-" + Guid.NewGuid().ToString("N").Substring(0, 8));
                Directory.CreateDirectory(tempRoot);
                SilentDebug.Log("Da tao thu muc tam: " + tempRoot);
                string serverDir = Path.Combine(tempRoot, "MangoServer");
                SilentDebug.Log("Giai nen resource " + InstallerCore.ServerResourceName + " -> " + serverDir + " ...");
                InstallerCore.ExtractResource(InstallerCore.ServerResourceName, serverDir);
                SilentDebug.Log("Da giai nen xong " + InstallerCore.ServerResourceName + ".");
                string pkgServer = File.Exists(Path.Combine(serverDir, "install_server.ps1")) ? serverDir : Path.Combine(serverDir, "MangoServer");
                SilentDebug.Log("pkgServer=" + pkgServer + ", install_server.ps1 ton tai=" + File.Exists(Path.Combine(pkgServer, "install_server.ps1")));
                string mangoDir = Path.Combine(tempRoot, "MangoMCPFull");
                SilentDebug.Log("Giai nen resource " + InstallerCore.MangoMCPResourceName + " -> " + mangoDir + " ...");
                InstallerCore.ExtractResource(InstallerCore.MangoMCPResourceName, mangoDir);
                SilentDebug.Log("Da giai nen xong " + InstallerCore.MangoMCPResourceName + ".");
                string pkgMango = Directory.Exists(Path.Combine(mangoDir, "MangoMCP")) ? Path.Combine(mangoDir, "MangoMCP") : mangoDir;
                SilentDebug.Log("pkgMango=" + pkgMango + ", ton tai=" + Directory.Exists(pkgMango));
                SilentDebug.Log("Goi install_server.ps1 ...");
                int code = InstallerCore.RunInstallPs(pkgServer, pkgMango, installDir, port, dataDir, password);
                SilentDebug.Log("install_server.ps1 thoat ma " + code + ".");
                string token = InstallerCore.ReadAndDeleteTokenFile();
                SilentDebug.Log("Doc token file: " + (string.IsNullOrEmpty(token) ? "khong co" : "co (khong ghi gia tri)") + ".");
                if (code != 0)
                {
                    string tail = InstallerCore.InstallLogTail();
                    SilentDebug.Log("Cai dat loi (ma " + code + "). Log cai dat (" + InstallerCore.InstallLogPath() + "): " + (string.IsNullOrEmpty(tail) ? "(khong co log)" : tail));
                }
                if (code == 0)
                {
                    var sb = new StringBuilder();
                    sb.AppendLine("Mango Server 1.2.1 - cai dat xong (silent).");
                    sb.AppendLine("Dashboard: http://127.0.0.1:" + port + "/dashboard");
                    sb.AppendLine("Data: " + dataDir);
                    if (generated)
                    {
                        sb.AppendLine("Mat khau quan tri (SINH NGAU NHIEN - luu lai ngay, chi hien o file nay):");
                        sb.AppendLine(password);
                    }
                    if (!string.IsNullOrEmpty(token))
                    {
                        sb.AppendLine("Token Agent toan quyen (CHI HIEN 1 LAN - luu lai ngay):");
                        sb.AppendLine(token);
                    }
                    sb.AppendLine("Nhat ky cai dat: " + InstallerCore.InstallLogPath());
                    File.WriteAllText(Path.Combine(Path.GetTempPath(), "MangoServer-install-creds.txt"), sb.ToString(), Encoding.UTF8);
                    SilentDebug.Log("Da ghi file thong tin: %TEMP%\\MangoServer-install-creds.txt (mat khau/token chi trong file nay, khong ghi vao log debug).");
                }
                SilentDebug.Log("Ket thuc silent install, ma thoat " + code + ".");
                return code;
            }
            catch (Exception ex)
            {
                SilentDebug.Log("EXCEPTION trong silent install: " + ex.ToString());
                try { File.WriteAllText(Path.Combine(Path.GetTempPath(), "MangoServer-install-error.txt"), ex.ToString(), Encoding.UTF8); } catch { }
                return 1;
            }
            finally
            {
                try { if (!string.IsNullOrEmpty(tempRoot) && Directory.Exists(tempRoot)) Directory.Delete(tempRoot, true); } catch { }
            }
        }
    }

    // Phan dung chung giua GUI va silent: giai nen resource, chay ps1.
    static class InstallerCore
    {
        public const string MangoMCPResourceName = "MangoMCPFull.zip";
        public const string ServerResourceName = "MangoServer.zip";

        public static string InstallLogPath()
        {
            return Path.Combine(Path.GetTempPath(), "MangoServer-install.log");
        }

        public static string TokenFilePath()
        {
            return Path.Combine(Path.GetTempPath(), "MangoServer-agent-token.txt");
        }

        public static string ReadAndDeleteTokenFile()
        {
            try
            {
                string path = TokenFilePath();
                if (!File.Exists(path)) return "";
                string token = File.ReadAllText(path).Trim();
                try { File.Delete(path); } catch { }
                return token;
            }
            catch { return ""; }
        }

        public static string InstallLogTail()
        {
            try
            {
                string path = InstallLogPath();
                if (!File.Exists(path)) return "";
                string[] lines = File.ReadAllLines(path);
                var keep = new System.Collections.Generic.List<string>();
                foreach (string raw in lines)
                {
                    string line = (raw ?? "").Trim();
                    if (line.Length == 0) continue;
                    if (line.StartsWith("Transcript started", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("Transcript stopped", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("Windows PowerShell transcript", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("Start time:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("End time:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("Username:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("Machine:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("Host Application:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("Process ID:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("PSVersion:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("PSEdition:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("PSCompatibleVersions:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("BuildVersion:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("CLRVersion:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("WSManStackVersion:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("PSRemotingProtocolVersion:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("SerializationVersion:", StringComparison.OrdinalIgnoreCase)) continue;
                    if (line.StartsWith("**********************", StringComparison.Ordinal)) continue;
                    keep.Add(line);
                }
                int start = Math.Max(0, keep.Count - 15);
                return string.Join("\n", keep.GetRange(start, keep.Count - start).ToArray());
            }
            catch { return ""; }
        }

        public static void ExtractResource(string resourceName, string destDir)
        {
            SilentDebug.Log("ExtractResource: " + resourceName + " -> " + destDir);
            Directory.CreateDirectory(destDir);
            string zipPath = Path.Combine(destDir, "__package.zip");
            Assembly asm = Assembly.GetExecutingAssembly();
            using (Stream rs = asm.GetManifestResourceStream(resourceName))
            {
                if (rs == null)
                {
                    SilentDebug.Log("ExtractResource LOI: khong tim thay resource " + resourceName + " trong exe (GetManifestResourceStream tra null). Cac resource co trong exe: " + string.Join(", ", asm.GetManifestResourceNames()));
                    throw new Exception("Khong tim thay goi nhung trong file exe nay: " + resourceName);
                }
                using (FileStream fs = File.Create(zipPath)) rs.CopyTo(fs);
            }
            int count = 0;
            using (ZipArchive archive = ZipFile.OpenRead(zipPath))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    count++;
                    string destPath = Path.GetFullPath(Path.Combine(destDir, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                    if (!destPath.StartsWith(Path.GetFullPath(destDir), StringComparison.OrdinalIgnoreCase)) continue;
                    if (string.IsNullOrEmpty(entry.Name))
                    {
                        Directory.CreateDirectory(destPath);
                    }
                    else
                    {
                        Directory.CreateDirectory(Path.GetDirectoryName(destPath));
                        using (Stream src = entry.Open())
                        using (FileStream dst = File.Create(destPath)) src.CopyTo(dst);
                    }
                }
            }
            SilentDebug.Log("ExtractResource xong: " + resourceName + " (" + count + " entries) -> " + destDir);
            try { File.Delete(zipPath); } catch { }
        }

        // Sinh mat khau ngau nhien 16 ky tu (chu + so, khong co ky tu gay
        // rac tren dong lenh). Chi dung khi nguoi cai de trong o mat khau.
        public static string RandomPassword(int length)
        {
            const string chars = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789";
            var rnd = new Random();
            var sb = new StringBuilder();
            for (int i = 0; i < length; i++) sb.Append(chars[rnd.Next(chars.Length)]);
            return sb.ToString();
        }

        // Chay install_server.ps1. Mat khau truyen qua bien moi truong cua
        // tien trinh con (khong nam tren dong lenh, khong vao transcript).
        // Tra ma thoat cua powershell.
        public static int RunInstallPs(string pkgServer, string pkgMango, string installDir, string port, string dataDir, string password)
        {
            string psFile = Path.Combine(pkgServer, "install_server.ps1");
            SilentDebug.Log("RunInstallPs: psFile=" + psFile + ", ton tai=" + File.Exists(psFile) + ", pkgMango=" + pkgMango + ", installDir=" + installDir + ", port=" + port + ", dataDir=" + dataDir + " (mat khau truyen qua bien moi truong, khong ghi vao log).");
            if (!File.Exists(psFile)) throw new Exception("Khong thay file cai dat trong goi server: " + psFile);
            try
            {
                var polPsi = new ProcessStartInfo("powershell.exe",
                    "-NoProfile -ExecutionPolicy Bypass -Command \"Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force\"");
                polPsi.UseShellExecute = false;
                var polProc = Process.Start(polPsi);
                polProc.WaitForExit();
                SilentDebug.Log("RunInstallPs: buoc Set-ExecutionPolicy xong, ma thoat " + polProc.ExitCode + ".");
            }
            catch (Exception ex)
            {
                SilentDebug.Log("RunInstallPs: buoc Set-ExecutionPolicy loi (bo qua, thu chay ps1 truc tiep): " + ex.Message);
            }
            string args = "-NoProfile -ExecutionPolicy Bypass -File \"" + psFile + "\""
                + " -MangoMCPDir \"" + pkgMango + "\""
                + " -ServerSrc \"" + pkgServer + "\""
                + " -InstallDir \"" + installDir + "\""
                + " -Port " + port
                + " -DataDir \"" + dataDir + "\"";
            SilentDebug.Log("RunInstallPs: khoi dong powershell.exe " + args);
            ProcessStartInfo psi = new ProcessStartInfo("powershell.exe", args);
            psi.UseShellExecute = false;
            psi.EnvironmentVariables["MANGO_ADMIN_PASSWORD"] = password ?? "";
            Process proc = Process.Start(psi);
            SilentDebug.Log("RunInstallPs: powershell da chay (PID " + proc.Id + "), dang doi ...");
            proc.WaitForExit();
            SilentDebug.Log("RunInstallPs: powershell thoat ma " + proc.ExitCode + ".");
            return proc.ExitCode;
        }
    }

    class SetupForm : Form
    {
        private readonly Label _status = new Label();
        private readonly Button _installBtn = new Button();
        private readonly Button _cancelBtn = new Button();
        private readonly TextBox _portBox = new TextBox();
        private readonly TextBox _dataBox = new TextBox();
        private readonly TextBox _passBox = new TextBox();
        private readonly TextBox _pass2Box = new TextBox();
        private System.Windows.Forms.Timer _closeTimer;

        public SetupForm()
        {
            Text = "Mango Server 1.2.1 — Cai dat Server";
            Width = 560; Height = 560;
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false; MinimizeBox = false;
            BackColor = Color.FromArgb(246, 243, 238);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            var logo = new PictureBox();
            logo.Image = MangoBitmap(56);
            logo.SizeMode = PictureBoxSizeMode.StretchImage;
            logo.Left = 24; logo.Top = 20; logo.Width = 56; logo.Height = 56;
            var title = new Label { Text = "Mango Server 1.2.1", Font = new Font("Segoe UI", 18, FontStyle.Bold), Left = 92, Top = 22, AutoSize = true };
            var sub = new Label { Text = "Server quan ly may Windows — tu chay lai sau khi khoi dong", Font = new Font("Segoe UI", 10), ForeColor = Color.FromArgb(107, 114, 128), Left = 92, Top = 56, Width = 440, Height = 20 };
            var desc = new Label
            {
                Text = "Bam Cai dat la xong. Server chay bang SYSTEM luc Windows khoi dong nen tu chay lai sau khi khoi dong may ma khong can ai dang nhap. Mo dashboard de duyet may con, lay ma dang ky, xem trang thai may.\nMuốn gỡ thì vào Windows Uninstall (Cài đặt > Ứng dụng) tìm \"Mango Server\".",
                Font = new Font("Segoe UI", 10), Left = 24, Top = 92, Width = 496, Height = 80
            };
            var portLbl = new Label { Text = "Cong:", Font = new Font("Segoe UI", 10), Left = 24, Top = 184, Width = 110, Height = 22 };
            _portBox.Text = "8443"; _portBox.Font = new Font("Segoe UI", 10);
            _portBox.Left = 140; _portBox.Top = 182; _portBox.Width = 100; _portBox.Height = 24;
            var portNote = new Label { Text = "Mac dinh 8443. Neu cong nay da co dich vu khac thi doi cong khac.", Font = new Font("Segoe UI", 9), ForeColor = Color.FromArgb(107, 114, 128), Left = 248, Top = 184, Width = 272, Height = 32 };
            var dataLbl = new Label { Text = "Thu muc data:", Font = new Font("Segoe UI", 10), Left = 24, Top = 214, Width = 110, Height = 22 };
            _dataBox.Text = @"C:\MangoMCPServer\data"; _dataBox.Font = new Font("Segoe UI", 10);
            _dataBox.Left = 140; _dataBox.Top = 212; _dataBox.Width = 300; _dataBox.Height = 24;
            var passLbl = new Label { Text = "Mat khau quan tri:", Font = new Font("Segoe UI", 10), Left = 24, Top = 244, Width = 140, Height = 22 };
            _passBox.UseSystemPasswordChar = true; _passBox.Font = new Font("Segoe UI", 10);
            _passBox.Left = 170; _passBox.Top = 242; _passBox.Width = 270; _passBox.Height = 24;
            var pass2Lbl = new Label { Text = "Nhap lai mat khau:", Font = new Font("Segoe UI", 10), Left = 24, Top = 274, Width = 140, Height = 22 };
            _pass2Box.UseSystemPasswordChar = true; _pass2Box.Font = new Font("Segoe UI", 10);
            _pass2Box.Left = 170; _pass2Box.Top = 272; _pass2Box.Width = 270; _pass2Box.Height = 24;
            var passNote = new Label
            {
                Text = "Dung de dang nhap dashboard. Chi luu dang hash tren may nay. De trong ca 2 o thi tu sinh mat khau ngau nhien va hien 1 lan sau khi cai xong — nho luu lai.",
                Font = new Font("Segoe UI", 9), ForeColor = Color.FromArgb(107, 114, 128), Left = 24, Top = 302, Width = 496, Height = 32
            };
            var info = new Label
            {
                Text = "May nay: " + Environment.MachineName + "\nCai vao: C:\\MangoMCPServer (code server + data mac dinh)",
                Font = new Font("Consolas", 10), ForeColor = Color.FromArgb(107, 114, 128), Left = 24, Top = 342, Width = 496, Height = 40
            };

            _installBtn.Text = "Cai dat"; _installBtn.Left = 24; _installBtn.Top = 392; _installBtn.Width = 230; _installBtn.Height = 42;
            _installBtn.FlatStyle = FlatStyle.Flat; _installBtn.FlatAppearance.BorderSize = 0;
            _installBtn.BackColor = Color.FromArgb(249, 115, 22); _installBtn.ForeColor = Color.White;
            _installBtn.Font = new Font("Segoe UI", 11, FontStyle.Bold); _installBtn.Cursor = Cursors.Hand;
            _installBtn.Click += (s, e) => RunInstall();

            _cancelBtn.Text = "Thoat"; _cancelBtn.Left = 266; _cancelBtn.Top = 392; _cancelBtn.Width = 100; _cancelBtn.Height = 42;
            _cancelBtn.FlatStyle = FlatStyle.Flat; _cancelBtn.BackColor = Color.White;
            _cancelBtn.Click += (s, e) => Close();
            CancelButton = _cancelBtn;

            _status.Text = ""; _status.Font = new Font("Segoe UI", 10); _status.ForeColor = Color.FromArgb(107, 114, 128);
            _status.Left = 24; _status.Top = 448; _status.Width = 496; _status.Height = 20;

            Controls.AddRange(new Control[] { logo, title, sub, desc, portLbl, _portBox, portNote, dataLbl, _dataBox, passLbl, _passBox, pass2Lbl, _pass2Box, passNote, info, _installBtn, _cancelBtn, _status });
        }

        private static Bitmap MangoBitmap(int size)
        {
            Bitmap bmp = new Bitmap(size, size);
            using (Graphics g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                float s = size;
                using (System.Drawing.Drawing2D.GraphicsPath leaf = new System.Drawing.Drawing2D.GraphicsPath())
                {
                    leaf.AddEllipse(s * 0.52f, s * 0.02f, s * 0.42f, s * 0.26f);
                    using (Brush lb = new SolidBrush(Color.FromArgb(34, 160, 107))) g.FillPath(lb, leaf);
                }
                RectangleF body = new RectangleF(s * 0.08f, s * 0.18f, s * 0.84f, s * 0.76f);
                using (System.Drawing.Drawing2D.LinearGradientBrush br = new System.Drawing.Drawing2D.LinearGradientBrush(body, Color.FromArgb(255, 197, 61), Color.FromArgb(234, 88, 12), 45f))
                    g.FillEllipse(br, body);
                using (Brush hi = new SolidBrush(Color.FromArgb(110, 255, 255, 255)))
                    g.FillEllipse(hi, s * 0.22f, s * 0.30f, s * 0.26f, s * 0.34f);
            }
            return bmp;
        }

        private void SetBusy(bool busy)
        {
            _installBtn.Enabled = !busy; _cancelBtn.Enabled = !busy;
            Application.DoEvents();
        }

        private void RunInstall()
        {
            string portText = (_portBox.Text ?? "").Trim();
            string dataDir = (_dataBox.Text ?? "").Trim();
            string pass = _passBox.Text ?? "";
            string pass2 = _pass2Box.Text ?? "";
            int port;
            if (!int.TryParse(portText, out port) || port < 1 || port > 65535)
            {
                MessageBox.Show("Cong khong hop le (phai la so 1..65535).", "Mango Server — Cong sai", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            if (string.IsNullOrWhiteSpace(dataDir))
            {
                MessageBox.Show("Chua nhap thu muc data.", "Mango Server — Thieu thu muc data", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            if (pass != pass2)
            {
                MessageBox.Show("Hai lan nhap mat khau khac nhau.", "Mango Server — Mat khau khac nhau", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            bool generated = false;
            if (string.IsNullOrEmpty(pass))
            {
                DialogResult dr = MessageBox.Show(
                    "De trong mat khau quan tri — se tu sinh mat khau ngau nhien va hien 1 lan sau khi cai xong.\n\nTiep tuc?",
                    "Mango Server — Sinh mat khau ngau nhien", MessageBoxButtons.OKCancel, MessageBoxIcon.Question);
                if (dr != DialogResult.OK) return;
                pass = InstallerCore.RandomPassword(16);
                generated = true;
            }
            else if (pass.Length < 4)
            {
                MessageBox.Show("Mat khau quan tri phai co it nhat 4 ky tu.", "Mango Server — Mat khau ngan", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            SetBusy(true);
            string tempRoot = "";
            try
            {
                _status.Text = "Dang giai nen goi cai dat, cho chut...";
                Application.DoEvents();
                tempRoot = Path.Combine(Path.GetTempPath(), "MangoServer-Setup-" + Guid.NewGuid().ToString("N").Substring(0, 8));
                Directory.CreateDirectory(tempRoot);

                string serverDir = Path.Combine(tempRoot, "MangoServer");
                InstallerCore.ExtractResource(InstallerCore.ServerResourceName, serverDir);
                string pkgServer = File.Exists(Path.Combine(serverDir, "install_server.ps1")) ? serverDir : Path.Combine(serverDir, "MangoServer");

                string mangoDir = Path.Combine(tempRoot, "MangoMCPFull");
                InstallerCore.ExtractResource(InstallerCore.MangoMCPResourceName, mangoDir);
                string pkgMango = Directory.Exists(Path.Combine(mangoDir, "MangoMCP")) ? Path.Combine(mangoDir, "MangoMCP") : mangoDir;

                _status.Text = "Dang cai dat...";
                Application.DoEvents();
                int code = InstallerCore.RunInstallPs(pkgServer, pkgMango, @"C:\MangoMCPServer", port.ToString(), dataDir, pass);
                string token = InstallerCore.ReadAndDeleteTokenFile();
                if (code != 0)
                {
                    string detail = InstallerCore.InstallLogTail();
                    string msg = "Cai dat ket thuc voi ma loi " + code + "."
                        + (string.IsNullOrEmpty(detail) ? "\nHay xem cua so PowerShell vua roi de biet chi tiet."
                        : "\n\nLoi ghi duoc:\n" + detail)
                        + "\n\nNhat ky day du: " + InstallerCore.InstallLogPath();
                    MessageBox.Show(msg, "Mango Server — Loi", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    SetBusy(false);
                    _status.Text = "";
                    return;
                }
                // Thanh cong: hien thong tin 1 lan (mat khau neu sinh ngau
                // nhien + token Agent neu tao moi). Khong tu dong dong cua
                // so — nguoi cai can thoi gian chep lai.
                _status.Text = "Cai dat Mango Server 1.2.1 xong!";
                _installBtn.Enabled = false; _cancelBtn.Enabled = false;
                Application.DoEvents();
                var sb = new StringBuilder();
                sb.AppendLine("Cai dat Mango Server 1.2.1 xong!");
                sb.AppendLine();
                sb.AppendLine("Dashboard: http://127.0.0.1:" + port + "/dashboard");
                sb.AppendLine("Thu muc data: " + dataDir);
                sb.AppendLine("Server tu chay lai sau khi khoi dong may (Task MangoServer, SYSTEM).");
                if (generated)
                {
                    sb.AppendLine();
                    sb.AppendLine("Mat khau quan tri (SINH NGAU NHIEN - luu lai ngay, chi hien 1 lan nay):");
                    sb.AppendLine(pass);
                }
                if (!string.IsNullOrEmpty(token))
                {
                    sb.AppendLine();
                    sb.AppendLine("Token Agent toan quyen (CHI HIEN 1 LAN NAY - luu lai ngay):");
                    sb.AppendLine(token);
                }
                sb.AppendLine();
                sb.AppendLine("Buoc tiep theo: mo dashboard, dang nhap, vao tab Ma dang ky de lay ma cho may con.");
                MessageBox.Show(sb.ToString(), "Mango Server — Cai dat xong", MessageBoxButtons.OK, MessageBoxIcon.Information);
                Close();
                return;
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "Mango Server — Loi", MessageBoxButtons.OK, MessageBoxIcon.Error);
                SetBusy(false);
                _status.Text = "";
            }
            finally
            {
                try { if (!string.IsNullOrEmpty(tempRoot) && Directory.Exists(tempRoot)) Directory.Delete(tempRoot, true); } catch { }
            }
        }
    }
}
