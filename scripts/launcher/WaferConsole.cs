using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

[assembly: AssemblyTitle("Wafer Console")]
[assembly: AssemblyDescription("Wafer File Viewer (Console)")]
[assembly: AssemblyProduct("Wafer")]
[assembly: AssemblyCopyright("Copyright (c) Wafer contributors")]

class Program
{
    static int Main(string[] args)
    {
        string exeDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string runtime = Path.Combine(exeDir, "python", "wafer-python.exe");
        string script = Path.Combine(exeDir, "main.py");
        if (!File.Exists(runtime))
        {
            Console.Error.WriteLine("Runtime not found: " + runtime);
            return 1;
        }
        string arguments = "\"" + script + "\"";
        foreach (string arg in args)
            arguments += " \"" + arg + "\"";
        ProcessStartInfo psi = new ProcessStartInfo
        {
            FileName = runtime,
            Arguments = arguments,
            WorkingDirectory = exeDir,
            UseShellExecute = false,
        };
        try
        {
            Process p = Process.Start(psi);
            p.WaitForExit();
            return p.ExitCode;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Failed to start: " + ex.Message);
            return 1;
        }
    }
}
