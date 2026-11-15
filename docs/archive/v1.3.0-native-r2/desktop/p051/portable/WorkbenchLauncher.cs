using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;
using System.Reflection;

[assembly: AssemblyVersion("1.3.0.0")]
[assembly: AssemblyFileVersion("1.3.0.0")]

internal static class WorkbenchLauncher
{
    // Windows command-line quoting must preserve quotes and trailing backslashes.
    private static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char character in value)
        {
            if (character == '\\')
            {
                backslashes++;
                continue;
            }
            result.Append('\\', character == '"' ? backslashes * 2 + 1 : backslashes);
            result.Append(character);
            backslashes = 0;
        }
        return result.Append('\\', backslashes * 2).Append('"').ToString();
    }

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            string root = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "app");
            string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
            string script = Path.Combine(root, "portable-launch.py");
            if (!File.Exists(python) || !File.Exists(script))
                throw new FileNotFoundException("运行文件缺失，请完整解压新版 ZIP，保留 EXE 同级 app 文件夹。\nExtract the complete ZIP and keep its app folder.\n\nPython: " + python + "\nLauncher: " + script + "\n\n运行 HRC-SelfCheck.cmd 可生成具体排错报告。\nRun HRC-SelfCheck.cmd for a diagnostic report.");

            var arguments = new StringBuilder("-B -X utf8 ").Append(Quote(script));
            foreach (string arg in args)
                arguments.Append(' ').Append(Quote(arg));

            var start = new ProcessStartInfo(python, arguments.ToString());
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            foreach (string variable in new[] { "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONEXE" })
                start.EnvironmentVariables.Remove(variable);
            using (var child = Process.Start(start))
            {
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "HRC Workbench", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
