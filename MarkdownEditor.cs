using System;
using System.Diagnostics;
using System.IO;

[assembly: System.Reflection.AssemblyTitle("Markdown Editor")]
[assembly: System.Reflection.AssemblyProduct("Markdown Editor")]
[assembly: System.Reflection.AssemblyDescription("Markdown Editor")]

// Tiny launcher shim: forwards the .md path to the bundled portable pythonw.
// Exists only so the Win11 Open With picker shows "Markdown Editor"
// (it reads FileDescription of the command exe) instead of "Python".
static class M
{
    static void Main(string[] args)
    {
        string here = AppDomain.CurrentDomain.BaseDirectory;
        string py = Path.Combine(here, "python", "pythonw.exe");
        string lp = Path.Combine(here, "md_launch.pyw");
        if (!File.Exists(py) || !File.Exists(lp)) return;
        string extra = (args != null && args.Length > 0 && args[0].Length > 0)
            ? " \"" + args[0] + "\"" : "";
        Process.Start(new ProcessStartInfo
        {
            FileName = py,
            Arguments = "\"" + lp + "\"" + extra,
            UseShellExecute = false
        });
    }
}
