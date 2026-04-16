using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

[assembly: AssemblyTitle("WaferConsole")]
[assembly: AssemblyDescription("Wafer File Viewer (Console)")]
[assembly: AssemblyProduct("Wafer")]
[assembly: AssemblyCopyright("Copyright (c) Wafer contributors")]

class Program
{
    static string EscapeArg(string s)
    {
        if (s.Length > 0 && s.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
            return s;
        string escaped = s.Replace("\\\"", "\\\\\"").Replace("\"", "\\\"");
        return "\"" + escaped + "\"";
    }

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
        string arguments = EscapeArg(script);
        foreach (string arg in args)
            arguments += " " + EscapeArg(arg);
        ProcessStartInfo psi = new ProcessStartInfo
        {
            FileName = runtime,
            Arguments = arguments,
            WorkingDirectory = exeDir,
            UseShellExecute = false,
        };
        try
        {
            using (Process proc = Process.Start(psi))
            {
                proc.WaitForExit();
                return proc.ExitCode;
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Failed to start: " + ex.Message);
            return 1;
        }
    }
}
