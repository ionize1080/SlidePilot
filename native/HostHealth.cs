using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;

namespace SlidePilot {
    internal static class HostHealth {
        static string FileFor(int pid) {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "SlidePilot", "health", pid.ToString(CultureInfo.InvariantCulture) + ".txt");
        }

        // Written by PowerPoint only after the Ribbon onLoad callback.
        internal static void RibbonLoaded(string folder) {
            try {
                using (var process = Process.GetCurrentProcess()) {
                    string file = FileFor(process.Id);
                    Directory.CreateDirectory(Path.GetDirectoryName(file));
                    File.WriteAllLines(file, new[] { process.StartTime.ToUniversalTime().Ticks.ToString(CultureInfo.InvariantCulture),
                        Path.GetFullPath(folder).TrimEnd(Path.DirectorySeparatorChar) }, Encoding.UTF8);
                }
            } catch (Exception) { /* Diagnostics must not interrupt Office startup. */ }
        }

        internal static bool IsLoaded(string folder) {
            string expected = Path.GetFullPath(folder).TrimEnd(Path.DirectorySeparatorChar);
            bool found = false;
            foreach (var process in Process.GetProcessesByName("POWERPNT")) {
                using (process) {
                    try {
                        var record = File.ReadAllLines(FileFor(process.Id), Encoding.UTF8);
                        found |= record.Length == 2 && record[0] == process.StartTime.ToUniversalTime().Ticks.ToString(CultureInfo.InvariantCulture)
                            && String.Equals(record[1], expected, StringComparison.OrdinalIgnoreCase);
                    } catch (Exception) { /* Another account or an unconnected host has no readable receipt. */ }
                }
            }
            return found;
        }

        internal static void Clear() {
            try { using (var process = Process.GetCurrentProcess()) File.Delete(FileFor(process.Id)); }
            catch (Exception) { }
        }
    }
}
