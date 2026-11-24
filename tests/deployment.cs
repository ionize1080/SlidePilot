using Microsoft.Win32;
using System;
using System.IO;
using System.Runtime.InteropServices;

// Redirect HKCU in this test process. The real Office registration is never changed.
class DeploymentTest {
    [DllImport("advapi32.dll")]
    static extern int RegOverridePredefKey(IntPtr predefined, IntPtr replacement);

    static int Main(string[] args) {
        if (args.Length != 1) return 2;
        string bundle = Path.GetFullPath(args[0]);
        string temporary = @"Software\SlidePilot-Deployment-QA-" + Guid.NewGuid().ToString("N");
        var hkcu = new IntPtr(unchecked((int)0x80000001));
        using (var user = RegistryKey.OpenBaseKey(RegistryHive.CurrentUser, RegistryView.Default))
        using (var sandbox = user.CreateSubKey(temporary, RegistryKeyPermissionCheck.ReadWriteSubTree,
                                               RegistryOptions.Volatile)) {
            int status = RegOverridePredefKey(hkcu, sandbox.Handle.DangerousGetHandle());
            if (status != 0) throw new System.ComponentModel.Win32Exception(status);
            try {
                var domain = AppDomain.CreateDomain("SlidePilot deployment", null,
                                                    new AppDomainSetup { ApplicationBase = bundle });
                try {
                    string manager = Path.Combine(bundle, "SlidePilot.Manager.exe");
                    string office = @"Software\Microsoft\Office\PowerPoint\Addins\SlidePilot.PowerPoint";
                    string neighbor = @"Software\Microsoft\Office\Word\Addins\PagePilot.QAFixture";
                    using (var k = sandbox.CreateSubKey(neighbor)) k.SetValue("Marker", "original");
                    foreach (var verb in new[] { "enable", "enable", "status", "disable", "disable" }) {
                        if (domain.ExecuteAssembly(manager, new[] { verb }) != 0)
                            throw new Exception("Manager failed: " + verb);
                        using (var k = sandbox.OpenSubKey(office)) {
                            if (verb == "disable" ? k != null : k == null || (int)k.GetValue("LoadBehavior") != 3)
                                throw new Exception("Incorrect PowerPoint add-in registration after " + verb);
                        }
                        using (var k = sandbox.OpenSubKey(neighbor)) {
                            if (k == null || (string)k.GetValue("Marker") != "original")
                                throw new Exception("Adjacent add-in registration changed");
                        }
                    }
                    Console.WriteLine("Isolated enable, status, disable and neighboring add-in checks passed.");
                } finally { AppDomain.Unload(domain); }
            } finally {
                RegOverridePredefKey(hkcu, IntPtr.Zero);
                user.DeleteSubKeyTree(temporary, false);
            }
        }
        return 0;
    }
}
