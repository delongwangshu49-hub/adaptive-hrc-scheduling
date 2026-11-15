using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

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
                throw new FileNotFoundException("Extract the complete ZIP and keep the app folder beside this EXE.");

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
