// MangoClient-Setup.exe — File cai dat duy nhat cua Mango Client 2.1.9.
// Cach dung tren may con: chi can copy 1 file MangoClient-Setup-2.1.9.exe
// sang may do, nhap tai khoan + mat khau (dung de dieu khien giao dien
// khi can), bam "Cai dat". Ten may tu lay tu ten may Windows, dia chi
// Server co san trong file cai, client tu enroll len Server. May se hien
// pending tren dashboard cho Quan tri vien duyet.
//
// Ban CustomHost (build voi -CustomHost, exe
// MangoClient-Setup-2.1.9-CustomHost.exe): them o nhap Server host/cong
// de cai vao Server khac; ban chuan khong co 2 o nay, C# truyen
// -ServerHost mac dinh (xem RunInstall) de cai zero-input.
//
// Co che: 1 goi zip duoc nhung san trong file exe duoi dang resource:
//   - MangoClient.zip : goi client 2.1.9 (run_client.py + gui_agent.py +
//     mangoclient/ + mangoengine/ + install_client.ps1 +
//     uninstall_client.ps1 + server-client.example.json) + goi MangoMCP
//     Full (chi lay thu muc python lam runtime, KHONG cai MangoMCP).
// Khi chay, app giai nen goi ra thu muc tam, roi chay install_client.ps1:
// copy code 2.1 vao C:\MangoClient\, ghi server-client.json (URL mac dinh
// + ten may tu dong + tai khoan da luu), tao Scheduled Task MangoClient
// (chay luc Windows khoi dong bang SYSTEM, an, pythonw.exe), dang ky
// Windows Uninstall, chay client lan dau — client tu enroll bang URL,
// hien pending tren dashboard cho Quan tri vien duyet.
// Sau khi xong, thu muc tam duoc don. File exe nay khong chua config that
// hay token that.
// Luu y: file exe CHI build duoc tren Windows (csc.exe + goi MangoMCP Full
// chi co tren may Windows).
using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;

namespace MangoClientSetup
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupForm());
        }
    }

    class SetupForm : Form
    {
        private readonly Label _status = new Label();
        private readonly Button _installBtn = new Button();
        private readonly Button _cancelBtn = new Button();
        private readonly TextBox _userBox = new TextBox();
        private readonly TextBox _passBox = new TextBox();
#if CUSTOM_HOST
        private readonly TextBox _hostBox = new TextBox();
        private readonly TextBox _portBox = new TextBox();
#endif
        private System.Windows.Forms.Timer _closeTimer;
        private const string MangoMCPResourceName = "MangoMCPFull.zip";
        private const string ClientResourceName = "MangoClient.zip";

        public SetupForm()
        {
#if CUSTOM_HOST
            Text = "Mango Client 2.1.9 (Custom Host) — Nối máy vào Mango Server";
#else
            Text = "Mango Client 2.1.9 — Nối máy vào Mango Server";
#endif
            Width = 560; Height = 480;
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false; MinimizeBox = false;
            BackColor = Color.FromArgb(246, 243, 238);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            var logo = new PictureBox();
            logo.Image = MangoLogo(56);
            logo.SizeMode = PictureBoxSizeMode.StretchImage;
            logo.Left = 24; logo.Top = 20; logo.Width = 56; logo.Height = 56;
            var title = new Label { Text = "Mango Client 2.1.9", Font = new Font("Segoe UI", 18, FontStyle.Bold), Left = 92, Top = 22, AutoSize = true };
            var sub = new Label { Text = "Nối máy này vào Mango Server — chạy ngay cả khi chưa đăng nhập", Font = new Font("Segoe UI", 10), ForeColor = Color.FromArgb(107, 114, 128), Left = 92, Top = 56, Width = 440, Height = 20 };
            var desc = new Label
            {
                Text = "Bấm Cài đặt là xong. Client chạy bằng SYSTEM lúc Windows khởi động nên điều khiển được bằng lệnh cmd/powershell ngay cả khi chưa ai đăng nhập. Tên máy tự lấy từ tên máy Windows, địa chỉ Server đã có sẵn trong file cài, client tự đăng ký lên Server.\nMáy sẽ tự hiện lên dashboard ở trạng thái chờ duyệt — Quản trị viên duyệt là nối được.\nMuốn gỡ thì vào Windows Uninstall (Cài đặt > Ứng dụng) tìm \"Mango Client\".",
                Font = new Font("Segoe UI", 10), Left = 24, Top = 92, Width = 496, Height = 80
            };
            var accTitle = new Label { Text = "Tài khoản dùng để điều khiển giao diện / màn hình khi cần:", Font = new Font("Segoe UI", 10, FontStyle.Bold), Left = 24, Top = 178, Width = 496, Height = 20 };
            var userLbl = new Label { Text = "Tên tài khoản:", Font = new Font("Segoe UI", 10), Left = 24, Top = 204, Width = 110, Height = 22 };
            _userBox.Text = Environment.UserName; _userBox.Font = new Font("Segoe UI", 10);
            _userBox.Left = 140; _userBox.Top = 202; _userBox.Width = 200; _userBox.Height = 24;
            var passLbl = new Label { Text = "Mật khẩu:", Font = new Font("Segoe UI", 10), Left = 24, Top = 234, Width = 110, Height = 22 };
            _passBox.UseSystemPasswordChar = true; _passBox.Font = new Font("Segoe UI", 10);
            _passBox.Left = 140; _passBox.Top = 232; _passBox.Width = 200; _passBox.Height = 24;
            var accNote = new Label
            {
                Text = "Lưu trên máy này, không gửi lên Server. Dùng khi cần điều khiển màn hình/chuột mà chưa ai đăng nhập. Đổi mật khẩu sau này qua MangoServer.",
                Font = new Font("Segoe UI", 9), ForeColor = Color.FromArgb(107, 114, 128), Left = 24, Top = 262, Width = 496, Height = 32
            };
            var info = new Label
            {
                // Chi hien ten may o day; dong "Server:" do tung ban tu
                // ghi ben duoi (#if CUSTOM_HOST / #else) de ban CustomHost
                // khong chua host mac dinh nao trong file exe.
                Text = "Máy này: " + Environment.MachineName,
                Font = new Font("Consolas", 10), ForeColor = Color.FromArgb(107, 114, 128), Left = 24, Top = 302, Width = 496, Height = 40
            };

            _installBtn.Text = "Cài đặt"; _installBtn.Left = 24; _installBtn.Top = 352; _installBtn.Width = 230; _installBtn.Height = 42;
            _installBtn.FlatStyle = FlatStyle.Flat; _installBtn.FlatAppearance.BorderSize = 0;
            _installBtn.BackColor = Color.FromArgb(249, 115, 22); _installBtn.ForeColor = Color.White;
            _installBtn.Font = new Font("Segoe UI", 11, FontStyle.Bold); _installBtn.Cursor = Cursors.Hand;
            _installBtn.Click += (s, e) => RunInstall();

            _cancelBtn.Text = "Thoát"; _cancelBtn.Left = 266; _cancelBtn.Top = 352; _cancelBtn.Width = 100; _cancelBtn.Height = 42;
            _cancelBtn.FlatStyle = FlatStyle.Flat; _cancelBtn.BackColor = Color.White;
            _cancelBtn.Click += (s, e) => Close();
            CancelButton = _cancelBtn; // Bam Esc cung dong cua so.

            _status.Text = ""; _status.Font = new Font("Segoe UI", 10); _status.ForeColor = Color.FromArgb(107, 114, 128);
            _status.Left = 24; _status.Top = 408; _status.Width = 496; _status.Height = 20;

            Controls.AddRange(new Control[] { logo, title, sub, desc, accTitle, userLbl, _userBox, passLbl, _passBox, accNote, info, _installBtn, _cancelBtn, _status });
#if CUSTOM_HOST
            // Ban CustomHost: doi nut xuong duoi de cho 2 o nhap Server
            // host/cong; ban chuan giu nguyen bo cuc cu (480px).
            Height = 540;
            desc.Text = "Bấm Cài đặt là xong. Client chạy bằng SYSTEM lúc Windows khởi động nên điều khiển được bằng lệnh cmd/powershell ngay cả khi chưa ai đăng nhập. Nhập Server host/cổng bên dưới — máy sẽ enroll vào đúng Server đó.\nMáy sẽ tự hiện lên dashboard ở trạng thái chờ duyệt — Quản trị viên duyệt là nối được.\nMuốn gỡ thì vào Windows Uninstall (Cài đặt > Ứng dụng) tìm \"Mango Client\".";
            info.Top = 372;
            // Ban CustomHost: khong hien host mac dinh nao — nguoi cai
            // phai nhap host cua Server minh (xem o nhap ben duoi).
            info.Text = "Máy này: " + Environment.MachineName + "\nServer: (nhập host/cổng bên dưới)";
            _installBtn.Top = 422; _cancelBtn.Top = 422;
            _status.Top = 478;
            var hostLbl = new Label { Text = "Server host:", Font = new Font("Segoe UI", 10), Left = 24, Top = 302, Width = 110, Height = 22 };
            _hostBox.Text = ""; _hostBox.Font = new Font("Segoe UI", 10);
            _hostBox.Left = 140; _hostBox.Top = 300; _hostBox.Width = 260; _hostBox.Height = 24;
            var portLbl = new Label { Text = "Cổng:", Font = new Font("Segoe UI", 10), Left = 24, Top = 332, Width = 110, Height = 22 };
            _portBox.Text = "8443"; _portBox.Font = new Font("Segoe UI", 10);
            _portBox.Left = 140; _portBox.Top = 330; _portBox.Width = 100; _portBox.Height = 24;
            var hostNote = new Label
            {
                Text = "Máy này sẽ enroll vào đúng Server đã nhập (ghi vào server-client.json). BẮT BUỘC nhập Server host — để trống sẽ báo lỗi và dừng cài đặt. Chỉ nhập host/IP trần (không https://, không :cổng).",
                Font = new Font("Segoe UI", 9), ForeColor = Color.FromArgb(107, 114, 128), Left = 248, Top = 332, Width = 272, Height = 32
            };
            Controls.AddRange(new Control[] { hostLbl, _hostBox, portLbl, _portBox, hostNote });
#else
            // Ban chuan (noi bo): hien Server mac dinh cua minh.
            info.Text = "Máy này: " + Environment.MachineName + "\nServer: https://your-server.example.com";
#endif
        }

        // Logo qua xoai that: lay icon nhung san trong file exe (mango.ico, qua
        // /win32icon luc build). Neu khong lay duoc thi ve tam bang MangoBitmap.
        private static Bitmap MangoLogo(int size)
        {
            try
            {
                Icon exeIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
                if (exeIcon != null)
                {
                    using (Icon sized = new Icon(exeIcon, size, size)) return sized.ToBitmap();
                }
            }
            catch { }
            return MangoBitmap(size);
        }

        private static Bitmap MangoBitmap(int size)
        {
            Bitmap bmp = new Bitmap(size, size);
            using (Graphics g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                float s = size;
                using (GraphicsPath leaf = new GraphicsPath())
                {
                    leaf.AddEllipse(s * 0.52f, s * 0.02f, s * 0.42f, s * 0.26f);
                    using (Brush lb = new SolidBrush(Color.FromArgb(34, 160, 107))) g.FillPath(lb, leaf);
                }
                RectangleF body = new RectangleF(s * 0.08f, s * 0.18f, s * 0.84f, s * 0.76f);
                using (LinearGradientBrush br = new LinearGradientBrush(body, Color.FromArgb(255, 197, 61), Color.FromArgb(234, 88, 12), 45f))
                    g.FillEllipse(br, body);
                using (Brush hi = new SolidBrush(Color.FromArgb(110, 255, 255, 255)))
                    g.FillEllipse(hi, s * 0.22f, s * 0.30f, s * 0.26f, s * 0.34f);
            }
            return bmp;
        }

        // Log cai dat do install_client.ps1 ghi (Start-Transcript).
        private static string InstallLogPath()
        {
            return Path.Combine(Path.GetTempPath(), "MangoClient-install.log");
        }

        // Lay ~15 dong cuoi co noi dung cua log cai dat de hien trong hop loi.
        private static string InstallLogTail()
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

        private void SetBusy(bool busy)
        {
            _installBtn.Enabled = !busy; _cancelBtn.Enabled = !busy;
            Application.DoEvents();
        }

        // Giai nen 1 resource zip ra thu muc dich (giai nen tay).
        private static void ExtractResource(string resourceName, string destDir)
        {
            Directory.CreateDirectory(destDir);
            string zipPath = Path.Combine(destDir, "__package.zip");
            Assembly asm = Assembly.GetExecutingAssembly();
            using (Stream rs = asm.GetManifestResourceStream(resourceName))
            {
                if (rs == null) throw new Exception("Không tìm thấy gói nhúng trong file exe này: " + resourceName);
                using (FileStream fs = File.Create(zipPath)) rs.CopyTo(fs);
            }
            using (ZipArchive archive = ZipFile.OpenRead(zipPath))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
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
            try { File.Delete(zipPath); } catch { }
        }

        // Quote 1 doi so cho command-line Windows (CreateProcess): chi dau "
        // moi duoc CommandLineToArgvW hieu la gioi han chuoi; dau ' la ky tu
        // thuong nen se dinh kem vao gia tri (LOI 2.1.0: PsQuote dung '...'
        // nen user luu thanh 'admin' -> LogonUser 1326 + config_set_user_password
        // USER_NOT_FOUND). Escape " thanh \" va gap doi backslash dung truoc
        // " hoac o cuoi chuoi, theo quy tac CommandLineToArgvW.
        private static string PsQuote(string s)
        {
            string v = s ?? "";
            var sb = new System.Text.StringBuilder();
            sb.Append('"');
            int bs = 0;
            foreach (char c in v)
            {
                if (c == '\\') { bs++; continue; }
                if (c == '"')
                {
                    for (int i = 0; i < bs * 2 + 1; i++) sb.Append('\\');
                    sb.Append('"');
                    bs = 0;
                }
                else
                {
                    for (int i = 0; i < bs; i++) sb.Append('\\');
                    bs = 0;
                    sb.Append(c);
                }
            }
            for (int i = 0; i < bs * 2; i++) sb.Append('\\');
            sb.Append('"');
            return sb.ToString();
        }

        private void RunInstall()
        {
            string guiUser = (_userBox.Text ?? "").Trim();
            string guiPass = _passBox.Text ?? "";
            if (string.IsNullOrEmpty(guiUser))
            {
                MessageBox.Show("Chưa nhập tên tài khoản. Tài khoản này dùng để điều khiển giao diện/màn hình khi cần.",
                    "Mango Client — Thiếu tài khoản", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            if (string.IsNullOrEmpty(guiPass))
            {
                DialogResult dr = MessageBox.Show(
                    "Chưa nhập mật khẩu. Tiếp tục mà không lưu mật khẩu?\n\nKhi đó điều khiển giao diện/màn hình chỉ chạy được khi đã có người đăng nhập tại máy.",
                    "Mango Client — Chưa có mật khẩu", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning);
                if (dr != DialogResult.OK) return;
            }
#if CUSTOM_HOST
            string serverHost = (_hostBox.Text ?? "").Trim();
            string serverPortText = (_portBox.Text ?? "").Trim();
            int serverPort = 8443;
            // 2.1.9: KHONG fallback ve host mac dinh nao nua. De trong
            // host thi bao loi ro rang va dung — khong duoc lang le dung
            // host cua rieng ai (loi ban 2.1.8: de trong thi tu dung
            // host mac dinh trong code).
            if (serverHost.Length == 0)
            {
                MessageBox.Show("Chưa nhập Server host. Nhập host/IP của Mango Server cần nối tới (vd may-chu.example.com hoặc 192.168.1.10), rồi bấm Cài đặt.",
                    "Mango Client — Thiếu Server host", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            if (!int.TryParse(serverPortText, out serverPort) || serverPort < 1 || serverPort > 65535)
            {
                MessageBox.Show("Cổng Server không hợp lệ (phải là số 1..65535).",
                    "Mango Client — Cổng sai", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            if (serverHost.IndexOfAny(new char[] { ' ', '/', '\\', ':' }) >= 0)
            {
                MessageBox.Show("Server host không hợp lệ (không chứa khoảng trắng, /, \\ hay :). Nhập host/IP trần, vd may-chu.example.com hoặc 192.168.1.10 (chưa hỗ trợ IPv6 ở ô này).",
                    "Mango Client — Host sai", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
#endif
            SetBusy(true);
            string tempRoot = "";
            try
            {
                _status.Text = "Đang giải nén gói cài đặt, chờ chút...";
                Application.DoEvents();
                tempRoot = Path.Combine(Path.GetTempPath(), "MangoClient-Setup-" + Guid.NewGuid().ToString("N").Substring(0, 8));
                Directory.CreateDirectory(tempRoot);

                string clientDir = Path.Combine(tempRoot, "MangoClient");
                ExtractResource(ClientResourceName, clientDir);
                string pkgClient = File.Exists(Path.Combine(clientDir, "install_client.ps1")) ? clientDir : Path.Combine(clientDir, "MangoClient");

                // Goi MangoMCP Full: chi lay thu muc python lam runtime (khong cai MangoMCP).
                string mangoDir = Path.Combine(tempRoot, "MangoMCPFull");
                ExtractResource(MangoMCPResourceName, mangoDir);
                string pkgMango = Directory.Exists(Path.Combine(mangoDir, "MangoMCP")) ? Path.Combine(mangoDir, "MangoMCP") : mangoDir;

                string psFile = Path.Combine(pkgClient, "install_client.ps1");
                if (!File.Exists(psFile)) throw new Exception("Không thấy file cài đặt trong gói client: " + psFile);
                // 2.1.3: May moi (PC3) mac dinh chan chay script (Restricted).
                // Dat ExecutionPolicy cho user hien tai truoc khi chay file
                // cai, de lan sau chay lai cung khong bi chan nua.
                try
                {
                    var polPsi = new ProcessStartInfo("powershell.exe",
                        "-NoProfile -ExecutionPolicy Bypass -Command \"Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force\"");
                    polPsi.UseShellExecute = false;
                    var polProc = Process.Start(polPsi);
                    polProc.WaitForExit();
                }
                catch { }
                _status.Text = "Đang cài đặt...";
                Application.DoEvents();
                string args = "-NoProfile -ExecutionPolicy Bypass -File \"" + psFile + "\""
                    + " -MangoMCPDir \"" + pkgMango + "\""
                    + " -ClientSrc \"" + pkgClient + "\""
                    + " -GuiUser " + PsQuote(guiUser)
                    + " -GuiPassword " + PsQuote(guiPass);
#if CUSTOM_HOST
                args += " -ServerHost " + PsQuote(serverHost)
                    + " -ServerPort " + serverPort;
#else
                // Ban chuan (dung cho may cua minh): truyen -ServerHost
                // mac dinh tuong minh de cai zero-input. Host mac dinh
                // nay chi co trong ban chuan (noi bo), KHONG co trong
                // ban CustomHost xuat ban.
                args += " -ServerHost " + PsQuote("your-server.example.com")
                    + " -ServerPort 8443";
#endif
                ProcessStartInfo psi = new ProcessStartInfo("powershell.exe", args);
                psi.UseShellExecute = false;
                Process proc = Process.Start(psi);
                proc.WaitForExit();
                if (proc.ExitCode != 0)
                {
                    string detail = InstallLogTail();
                    string msg = "Cài đặt kết thúc với mã lỗi " + proc.ExitCode + "."
                        + (string.IsNullOrEmpty(detail) ? "\nHãy xem cửa sổ PowerShell vừa rồi để biết chi tiết."
                        : "\n\nLỗi ghi được:\n" + detail)
                        + "\n\nNhật ký đầy đủ: " + InstallLogPath();
                    MessageBox.Show(msg, "Mango Client — Lỗi", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
                else
                {
                    // 2.1.1: TU DONG DONG cua so sau khi cai xong (khong cho hop
                    // thoai modal). Ban 2.1.0 dung MessageBox "Xong" — phai bam
                    // OK moi dong, Quan tri vien khong bam thi cua so van mo va an phim
                    // go vao o nhap tai khoan/mat khau. Hien trang thai "xong"
                    // 2.5 giay roi dong bang timer.
                    _status.Text = "Cài đặt Mango Client 2.1.9 xong! Tài khoản '" + guiUser + "' đã lưu; máy đang tự enroll lên Server — vào dashboard duyệt là nối được. Cửa sổ sẽ tự đóng...";
                    _installBtn.Enabled = false; _cancelBtn.Enabled = false;
                    Application.DoEvents();
                    if (_closeTimer != null) { _closeTimer.Stop(); _closeTimer.Dispose(); }
                    _closeTimer = new System.Windows.Forms.Timer();
                    _closeTimer.Interval = 2500;
                    _closeTimer.Tick += (s2, e2) => { _closeTimer.Stop(); _closeTimer.Dispose(); Close(); };
                    _closeTimer.Start();
                    return;
                }
                Close();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "Mango Client — Lỗi", MessageBoxButtons.OK, MessageBoxIcon.Error);
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
