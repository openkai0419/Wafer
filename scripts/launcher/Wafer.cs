using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Wafer")]
[assembly: AssemblyDescription("Wafer File Viewer")]
[assembly: AssemblyProduct("Wafer")]
[assembly: AssemblyCopyright("Copyright (c) Wafer contributors")]

class Program
{
    const string UpdateDirName = ".update";
    const string PlanFileName = "apply.plan";
    const string ReadyFileName = "ready.json";
    const string AppliedFileName = "applied.txt";
    const string FailedFileName = "failed.txt";
    const string LogFileName = "apply.log";
    const string NextDirName = "next";
    const string BackupDirName = "backup";
    const string PlanHeader = "wafer-update-plan 1";
    const string LauncherExeName = "Wafer.exe";
    const string HelperDirPrefix = "Wafer-helper-";
    const string ApplyModeFlag = "--wafer-apply";
    const string UninstallModeFlag = "--wafer-uninstall";
    const string NoLaunchFlag = "--wafer-no-launch";
    const string AppDataDirName = "Wafer";
    const string UninstallerTitle = "Wafer Uninstaller";
    const int DefaultWaitSeconds = 15;

    static string logPath;

    static string EscapeArg(string s)
    {
        if (s.Length > 0 && s.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
            return s;
        string escaped = s.Replace("\\\"", "\\\\\"").Replace("\"", "\\\"");
        return "\"" + escaped + "\"";
    }

    static void Log(string message)
    {
        try
        {
            if (logPath != null)
                File.AppendAllText(logPath, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + message + Environment.NewLine);
        }
        catch (Exception) { }
    }

    static int WaitSeconds()
    {
        string raw = Environment.GetEnvironmentVariable("WAFER_UPDATE_WAIT_SECONDS");
        int value;
        if (raw != null && int.TryParse(raw, out value) && value >= 0)
            return value;
        return DefaultWaitSeconds;
    }

    static bool OtherAppProcessesRunning(string exeDir)
    {
        string prefix = exeDir.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        int ownPid = Process.GetCurrentProcess().Id;
        foreach (Process p in Process.GetProcesses())
        {
            try
            {
                if (p.Id == ownPid)
                    continue;
                string path = p.MainModule.FileName;
                if (path != null && path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                {
                    Log("Busy: process " + p.Id + " (" + path + ") is still running");
                    return true;
                }
            }
            catch (Exception) { }
            finally
            {
                p.Dispose();
            }
        }
        return false;
    }

    static bool WaitForExclusiveAccess(string exeDir)
    {
        int deadlineMs = WaitSeconds() * 1000;
        Stopwatch sw = Stopwatch.StartNew();
        while (true)
        {
            if (!OtherAppProcessesRunning(exeDir))
                return true;
            if (sw.ElapsedMilliseconds >= deadlineMs)
                return false;
            Thread.Sleep(500);
        }
    }

    static string ValidateRelPath(string raw)
    {
        string value = (raw ?? "").Trim().Replace('/', Path.DirectorySeparatorChar);
        if (value.Length == 0)
            throw new InvalidDataException("empty path in plan");
        if (Path.IsPathRooted(value) || value.Contains(":"))
            throw new InvalidDataException("path must be relative: " + raw);
        foreach (string part in value.Split(Path.DirectorySeparatorChar))
        {
            if (part == "" || part == "." || part == "..")
                throw new InvalidDataException("unsafe path in plan: " + raw);
        }
        return value;
    }

    class PlanOp
    {
        public bool Optional;
        public string Src;
        public string Dst;
    }

    static List<PlanOp> ReadPlan(string planPath)
    {
        string[] lines = File.ReadAllLines(planPath);
        if (lines.Length == 0 || lines[0].Trim() != PlanHeader)
            throw new InvalidDataException("unsupported plan header");
        List<PlanOp> ops = new List<PlanOp>();
        for (int i = 1; i < lines.Length; i++)
        {
            string line = lines[i].Trim();
            if (line.Length == 0)
                continue;
            string[] fields = line.Split('\t');
            if (fields.Length != 4 || fields[0] != "move" || (fields[1] != "0" && fields[1] != "1"))
                throw new InvalidDataException("invalid plan line: " + line);
            ops.Add(new PlanOp
            {
                Optional = fields[1] == "1",
                Src = ValidateRelPath(fields[2]),
                Dst = ValidateRelPath(fields[3]),
            });
        }
        return ops;
    }

    static void MovePath(string src, string dst)
    {
        string parent = Path.GetDirectoryName(dst);
        if (parent != null && !Directory.Exists(parent))
            Directory.CreateDirectory(parent);
        if (Directory.Exists(src))
            Directory.Move(src, dst);
        else
            File.Move(src, dst);
    }

    static bool PathExists(string path)
    {
        return Directory.Exists(path) || File.Exists(path);
    }

    static void Rollback(List<KeyValuePair<string, string>> executed)
    {
        for (int i = executed.Count - 1; i >= 0; i--)
        {
            try
            {
                MovePath(executed[i].Value, executed[i].Key);
            }
            catch (Exception ex)
            {
                Log("Rollback failed for " + executed[i].Value + " -> " + executed[i].Key + ": " + ex.Message);
            }
        }
    }

    static bool ApplyPendingUpdate(string appRoot)
    {
        string updateDir = Path.Combine(appRoot, UpdateDirName);
        string planPath = Path.Combine(updateDir, PlanFileName);
        if (!File.Exists(planPath))
        {
            Log("No pending update plan found");
            return false;
        }
        string version = ReadTargetVersion(Path.Combine(updateDir, ReadyFileName));
        if (version == null)
        {
            DiscardIncompleteStaging(updateDir, planPath);
            return false;
        }
        Log("Pending update v" + version + " found, preparing to apply");

        if (!WaitForExclusiveAccess(appRoot))
        {
            Log("Skipped: other Wafer processes are still running, will retry on next start");
            return false;
        }

        List<PlanOp> ops;
        try
        {
            ops = ReadPlan(planPath);
        }
        catch (Exception ex)
        {
            Log("Invalid plan, discarding: " + ex.Message);
            File.WriteAllText(Path.Combine(updateDir, FailedFileName), "invalid plan: " + ex.Message);
            TryDelete(planPath);
            TryDelete(Path.Combine(updateDir, ReadyFileName));
            return false;
        }

        string backupDir = Path.Combine(updateDir, BackupDirName);
        try
        {
            if (Directory.Exists(backupDir))
                Directory.Delete(backupDir, true);
        }
        catch (Exception ex)
        {
            Log("Skipped: could not clear previous backup: " + ex.Message);
            return false;
        }

        List<KeyValuePair<string, string>> executed = new List<KeyValuePair<string, string>>();
        try
        {
            foreach (PlanOp op in ops)
            {
                string src = Path.Combine(appRoot, op.Src);
                string dst = Path.Combine(appRoot, op.Dst);
                if (!PathExists(src))
                {
                    if (op.Optional)
                        continue;
                    throw new IOException("required source missing: " + op.Src);
                }
                if (PathExists(dst))
                {
                    if (op.Optional)
                        continue;
                    throw new IOException("destination already exists: " + op.Dst);
                }
                MovePath(src, dst);
                executed.Add(new KeyValuePair<string, string>(src, dst));
            }
        }
        catch (Exception ex)
        {
            Log("Apply failed: " + ex.Message + " - rolling back " + executed.Count + " operations");
            Rollback(executed);
            File.WriteAllText(Path.Combine(updateDir, FailedFileName), ex.Message);
            TryDelete(planPath);
            TryDelete(Path.Combine(updateDir, ReadyFileName));
            Log("Rollback complete, previous version restored");
            return false;
        }

        TryDelete(planPath);
        TryDelete(Path.Combine(updateDir, ReadyFileName));
        try
        {
            string nextDir = Path.Combine(updateDir, NextDirName);
            if (Directory.Exists(nextDir))
                Directory.Delete(nextDir, true);
        }
        catch (Exception ex)
        {
            Log("Cleanup of staged files failed: " + ex.Message);
        }
        File.WriteAllText(Path.Combine(updateDir, AppliedFileName), version);
        Log("Update applied successfully: " + version);
        return true;
    }

    static string ReadTargetVersion(string readyPath)
    {
        try
        {
            string text = File.ReadAllText(readyPath);
            string marker = "\"target_version\"";
            int idx = text.IndexOf(marker, StringComparison.Ordinal);
            if (idx >= 0)
            {
                int start = text.IndexOf('"', idx + marker.Length + 1);
                if (start >= 0)
                {
                    int end = text.IndexOf('"', start + 1);
                    if (end > start + 1)
                        return text.Substring(start + 1, end - start - 1);
                }
            }
        }
        catch (Exception) { }
        return null;
    }

    static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
                File.Delete(path);
        }
        catch (Exception ex)
        {
            Log("Failed to delete " + path + ": " + ex.Message);
        }
    }

    static bool StartProcess(string fileName, string[] args, string workingDir)
    {
        string arguments = "";
        foreach (string arg in args)
            arguments += (arguments.Length > 0 ? " " : "") + EscapeArg(arg);
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                WorkingDirectory = workingDir,
                UseShellExecute = false,
            });
            return true;
        }
        catch (Exception ex)
        {
            Log("Failed to start " + fileName + ": " + ex.Message);
            return false;
        }
    }

    static int LaunchApp(string appRoot, string[] args)
    {
        string runtime = Path.Combine(appRoot, "python", "wafer-pythonw.exe");
        string script = Path.Combine(appRoot, "main.py");
        if (!File.Exists(runtime))
        {
            Console.Error.WriteLine("Runtime not found: " + runtime);
            Log("Runtime not found: " + runtime);
            return 1;
        }
        List<string> launchArgs = new List<string>();
        launchArgs.Add(script);
        launchArgs.AddRange(args);
        if (StartProcess(runtime, launchArgs.ToArray(), appRoot))
            return 0;
        Console.Error.WriteLine("Failed to start: " + runtime);
        return 1;
    }

    static string[] ExtractForwardArgs(string[] args, int modeIdx)
    {
        List<string> forwarded = new List<string>();
        for (int i = 0; i < args.Length; i++)
        {
            if (i == modeIdx || i == modeIdx + 1)
                continue;
            forwarded.Add(args[i]);
        }
        return forwarded.ToArray();
    }

    static void DiscardIncompleteStaging(string updateDir, string planPath)
    {
        Log("Discarding staged update: " + ReadyFileName + " is missing or invalid");
        try
        {
            File.WriteAllText(Path.Combine(updateDir, FailedFileName), "staging incomplete: " + ReadyFileName + " is missing or invalid");
        }
        catch (Exception ex)
        {
            Log("Failed to write " + FailedFileName + ": " + ex.Message);
        }
        TryDelete(planPath);
        TryDelete(Path.Combine(updateDir, ReadyFileName));
    }

    static void CleanupStaleHelpers()
    {
        try
        {
            foreach (string dir in Directory.GetDirectories(Path.GetTempPath(), HelperDirPrefix + "*"))
            {
                try { Directory.Delete(dir, true); }
                catch (Exception) { }
            }
        }
        catch (Exception) { }
    }

    static bool StartApplyHelper(string exeDir, string[] args)
    {
        string source = Path.Combine(exeDir, UpdateDirName, NextDirName, LauncherExeName);
        if (!File.Exists(source))
            source = Assembly.GetExecutingAssembly().Location;
        try
        {
            string helperDir = Path.Combine(Path.GetTempPath(), HelperDirPrefix + Process.GetCurrentProcess().Id);
            Directory.CreateDirectory(helperDir);
            string helperExe = Path.Combine(helperDir, LauncherExeName);
            File.Copy(source, helperExe, true);
            List<string> helperArgs = new List<string>();
            helperArgs.Add(ApplyModeFlag);
            helperArgs.Add(exeDir);
            helperArgs.AddRange(args);
            if (!StartProcess(helperExe, helperArgs.ToArray(), helperDir))
                return false;
            Log("Handed off update apply to helper: " + helperExe);
            return true;
        }
        catch (Exception ex)
        {
            Log("Failed to start update helper: " + ex.Message);
            return false;
        }
    }

    static int RunLauncherMode(string exeDir, string[] args)
    {
        CleanupStaleHelpers();
        string updateDir = Path.Combine(exeDir, UpdateDirName);
        string planPath = Path.Combine(updateDir, PlanFileName);
        if (File.Exists(planPath))
        {
            logPath = Path.Combine(updateDir, LogFileName);
            if (ReadTargetVersion(Path.Combine(updateDir, ReadyFileName)) != null)
            {
                if (StartApplyHelper(exeDir, args))
                    return 0;
                Log("Could not start update helper, launching current version");
            }
            else
            {
                DiscardIncompleteStaging(updateDir, planPath);
            }
        }
        return LaunchApp(exeDir, args);
    }

    static int RunApplyMode(string appRoot, string[] forwardArgs)
    {
        bool noLaunch = false;
        List<string> launchArgs = new List<string>();
        foreach (string arg in forwardArgs)
        {
            if (arg == NoLaunchFlag)
                noLaunch = true;
            else
                launchArgs.Add(arg);
        }
        logPath = Path.Combine(appRoot, UpdateDirName, LogFileName);
        bool applied = false;
        try
        {
            applied = ApplyPendingUpdate(appRoot);
        }
        catch (Exception ex)
        {
            Log("Unexpected updater error: " + ex.Message);
        }
        if (noLaunch)
            return applied ? 0 : 1;
        if (applied && StartProcess(Path.Combine(appRoot, LauncherExeName), launchArgs.ToArray(), appRoot))
            return 0;
        return LaunchApp(appRoot, launchArgs.ToArray());
    }

    static string UserDataDir()
    {
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), AppDataDirName);
    }

    static bool ConfirmUninstall(string appRoot, out bool deleteUserData)
    {
        using (Form form = new Form())
        using (Label label = new Label())
        using (CheckBox userDataCheck = new CheckBox())
        using (Button okButton = new Button())
        using (Button cancelButton = new Button())
        {
            form.Text = UninstallerTitle;
            form.FormBorderStyle = FormBorderStyle.FixedDialog;
            form.MaximizeBox = false;
            form.MinimizeBox = false;
            form.ShowInTaskbar = true;
            form.StartPosition = FormStartPosition.CenterScreen;
            form.ClientSize = new Size(480, 172);

            label.Text = "Uninstall Wafer?\n\nThis removes the install folder:\n" + appRoot;
            label.SetBounds(16, 16, 448, 76);

            userDataCheck.Text = "Also delete user data (settings, database, cache)";
            userDataCheck.Checked = true;
            userDataCheck.SetBounds(16, 96, 448, 24);

            okButton.Text = "Uninstall";
            okButton.DialogResult = DialogResult.OK;
            okButton.SetBounds(296, 132, 80, 26);

            cancelButton.Text = "Cancel";
            cancelButton.DialogResult = DialogResult.Cancel;
            cancelButton.SetBounds(384, 132, 80, 26);

            form.Controls.Add(label);
            form.Controls.Add(userDataCheck);
            form.Controls.Add(okButton);
            form.Controls.Add(cancelButton);
            form.AcceptButton = okButton;
            form.CancelButton = cancelButton;

            bool confirmed = form.ShowDialog() == DialogResult.OK;
            deleteUserData = userDataCheck.Checked;
            return confirmed;
        }
    }

    static int RunUninstallMode(string appRoot)
    {
        Application.EnableVisualStyles();
        if (!Directory.Exists(appRoot))
        {
            MessageBox.Show("Install folder not found: " + appRoot, UninstallerTitle, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        bool deleteUserData;
        if (!ConfirmUninstall(appRoot, out deleteUserData))
            return 0;
        while (OtherAppProcessesRunning(appRoot))
        {
            DialogResult choice = MessageBox.Show(
                "Wafer is still running. Close all Wafer windows and retry.",
                UninstallerTitle, MessageBoxButtons.RetryCancel, MessageBoxIcon.Warning);
            if (choice != DialogResult.Retry)
                return 0;
        }
        try
        {
            Directory.Delete(appRoot, true);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "Failed to remove the install folder:\n" + ex.Message + "\n\nRemove the remaining files manually:\n" + appRoot,
                UninstallerTitle, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        string summary = "Wafer has been uninstalled.";
        if (deleteUserData)
        {
            string dataDir = UserDataDir();
            try
            {
                if (Directory.Exists(dataDir))
                    Directory.Delete(dataDir, true);
            }
            catch (Exception ex)
            {
                summary += "\n\nUser data could not be fully removed: " + ex.Message + "\n" + dataDir;
            }
        }
        MessageBox.Show(summary, UninstallerTitle, MessageBoxButtons.OK, MessageBoxIcon.Information);
        return 0;
    }

    [STAThread]
    static int Main(string[] args)
    {
        int idx = Array.IndexOf(args, ApplyModeFlag);
        if (idx >= 0)
        {
            if (idx + 1 >= args.Length)
            {
                Console.Error.WriteLine("Usage: Wafer.exe " + ApplyModeFlag + " <appRoot> [args...]");
                return 1;
            }
            return RunApplyMode(Path.GetFullPath(args[idx + 1]), ExtractForwardArgs(args, idx));
        }
        idx = Array.IndexOf(args, UninstallModeFlag);
        if (idx >= 0)
        {
            if (idx + 1 >= args.Length)
            {
                Console.Error.WriteLine("Usage: Wafer.exe " + UninstallModeFlag + " <appRoot>");
                return 1;
            }
            return RunUninstallMode(Path.GetFullPath(args[idx + 1]));
        }
        string exeDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        return RunLauncherMode(exeDir, args);
    }
}
