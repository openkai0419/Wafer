using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Wafer Uninstaller")]
[assembly: AssemblyDescription("Wafer File Viewer Uninstaller")]
[assembly: AssemblyProduct("Wafer")]
[assembly: AssemblyCopyright("Copyright (c) Wafer contributors")]

class Uninstaller
{
    const string LauncherExeName = "Wafer.exe";
    const string HelperDirPrefix = "Wafer-helper-";
    const string UninstallModeFlag = "--wafer-uninstall";
    const string Title = "Wafer Uninstaller";

    [STAThread]
    static int Main()
    {
        string exeDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string launcher = Path.Combine(exeDir, LauncherExeName);
        if (!File.Exists(launcher))
        {
            MessageBox.Show(LauncherExeName + " not found next to the uninstaller.", Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        try
        {
            string helperDir = Path.Combine(Path.GetTempPath(), HelperDirPrefix + Process.GetCurrentProcess().Id);
            Directory.CreateDirectory(helperDir);
            string helperExe = Path.Combine(helperDir, LauncherExeName);
            File.Copy(launcher, helperExe, true);
            Process.Start(new ProcessStartInfo
            {
                FileName = helperExe,
                Arguments = UninstallModeFlag + " \"" + exeDir + "\"",
                WorkingDirectory = helperDir,
                UseShellExecute = false,
            });
        }
        catch (Exception ex)
        {
            MessageBox.Show("Failed to start the uninstaller: " + ex.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        return 0;
    }
}
