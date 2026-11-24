using Microsoft.Win32;
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using SlidePilot;
class MachineScopeTest {
    [DllImport("advapi32.dll")] static extern int RegOverridePredefKey(IntPtr key,IntPtr replacement);
    static void Check(bool condition,string name) {if(!condition)throw new Exception(name);Console.WriteLine("PASS "+name);}
    static void CheckCodebase() {
        string literal=Manager.Codebase(@"C:\SlidePilot QA");
        Check(literal=="file:///C:/SlidePilot QA/SlidePilot.PowerPoint.dll","RegAsm CodeBase representation");
        Check(Manager.SameCodebase(literal,"file:///C:/SlidePilot%20QA/SlidePilot.PowerPoint.dll"),"legacy encoded spaces match");
        Check(Manager.SameCodebase(literal,"file:///c:/slidepilot qa/SLIDEPILOT.POWERPOINT.DLL"),"Windows case-insensitive path ownership");
        Check(!Manager.SameCodebase(literal,"file:///C:/SlidePilot%2520QA/SlidePilot.PowerPoint.dll"),"literal percent name stays distinct");
        Check(!Manager.SameCodebase(literal,"file:///C:/SlidePilot QA/Other.dll"),"different DLL does not match");
        Check(!Manager.SameCodebase(literal,"https://example.test/SlidePilot.PowerPoint.dll"),"non-file URI rejected");
        Check(!Manager.SameCodebase(null,literal),"missing registration is not owned");
        Check(!Manager.SameCodebase(literal,literal+"?other"),"file URI query is not an ownership match");
    }
    static string Hash(string path) {using(var sha=SHA256.Create())using(var file=File.OpenRead(path))return BitConverter.ToString(sha.ComputeHash(file)).Replace("-","").ToLowerInvariant();}
    static string Manifest(string root) {
        var text=new StringBuilder();
        foreach(string file in Manager.RequiredFiles)text.Append(Hash(Path.Combine(root,file))).Append("  ").Append(file.Replace('\\','/')).Append('\n');
        return text.ToString();
    }
    static void InvalidPackage(string root,string text,string name) {
        File.WriteAllText(Path.Combine(root,"manifest.sha256"),text,new UTF8Encoding(false));
        try{Manager.ValidatePackage(root);}catch(InvalidDataException){Check(true,name);return;}catch(IOException){Check(true,name);return;}
        throw new Exception("Accepted invalid package: "+name);
    }
    static int CheckPackage() {
        string root=Path.Combine(Path.GetTempPath(),"SlidePilot-package-QA-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try {
            foreach(string file in Manager.RequiredFiles) {string path=Path.Combine(root,file);Directory.CreateDirectory(Path.GetDirectoryName(path));File.WriteAllText(path,"QA placeholder: "+file);}
            string valid=Manifest(root);string manifest=Path.Combine(root,"manifest.sha256");
            File.WriteAllText(manifest,valid,new UTF8Encoding(false));
            Check(Manager.ValidatePackage(root)==Manager.RequiredFiles.Length,"all listed files hash verified");
            File.WriteAllText(Path.Combine(root,"unrelated-tool.exe"),"user file outside release inventory");
            Check(Manager.ValidatePackage(root)==Manager.RequiredFiles.Length,"extra user files are permitted");
            string first=valid.Substring(0,valid.IndexOf('\n')+1);
            InvalidPackage(root,valid+first.ToUpperInvariant(),"case-insensitive duplicate path rejected");
            InvalidPackage(root,valid+new string('0',64)+"  manifest.sha256\n","self-hash rejected");
            foreach(string path in new[]{"../outside","/absolute","C:/absolute","a\\b","a//b","a/./b","NUL.txt","COM¹.exe","a. /b","a/b "})
                InvalidPackage(root,new string('0',64)+"  "+path+"\n","unsafe path rejected: "+path);
            InvalidPackage(root,valid.Substring(first.Length),"required file omitted from manifest rejected");
            InvalidPackage(root,"bad manifest\n","invalid hash format rejected");
            File.AppendAllText(Path.Combine(root,Manager.RequiredFiles[0]),"tampered");
            InvalidPackage(root,valid,"changed payload rejected");
            return 0;
        } finally {Directory.Delete(root,true);}
    }
    static int Main(string[] args) {
        if(args.Length!=1){Console.Error.WriteLine("deployment_scopes.exe <portable-bundle-folder>");return 2;}
        try{CheckCodebase();return args[0]=="--paths"?0:args[0]=="--files"?CheckPackage():Run(args[0]);}
        catch(UnauthorizedAccessException e){Console.Error.WriteLine("Registry QA could not run in this environment: "+e.Message);return 3;}
        catch(Exception e){Console.Error.WriteLine(e);return 1;}
    }
    static int Run(string bundle) {
        string temporary=@"Software\SlidePilot-Machine-Scope-QA-"+Guid.NewGuid().ToString("N");
        var hkcu=new IntPtr(unchecked((int)0x80000001));var hklm=new IntPtr(unchecked((int)0x80000002));
        using(var realUser=RegistryKey.OpenBaseKey(RegistryHive.CurrentUser,RegistryView.Default))
        using(var sandbox=realUser.CreateSubKey(temporary,RegistryKeyPermissionCheck.ReadWriteSubTree,RegistryOptions.Volatile))
        using(var user=sandbox.CreateSubKey("User"))using(var machine=sandbox.CreateSubKey("Machine")) {
            bool redirectedUser=false,redirectedMachine=false;
            try {
                int code=RegOverridePredefKey(hkcu,user.Handle.DangerousGetHandle());if(code!=0)throw new System.ComponentModel.Win32Exception(code);redirectedUser=true;
                code=RegOverridePredefKey(hklm,machine.Handle.DangerousGetHandle());if(code!=0)throw new System.ComponentModel.Win32Exception(code);redirectedMachine=true;
                string root=Path.GetFullPath(bundle);
                string neighbor=@"Software\Microsoft\Office\Word\Addins\PagePilot.QA";
                using(var key=user.CreateSubKey(neighbor))key.SetValue("Marker","keep");
                using(var key=machine.CreateSubKey(neighbor))key.SetValue("Marker","keep-machine");
                var log=new StringWriter();
                Check(Manager.Run("enable",root,log)==0,"enable user");
                foreach(var view in Manager.Views)Check(Manager.RegistrationComplete(view,root,false),"both COM classes registered: "+view);
                Check(Manager.HasUserOverride(),"detect user override");
                Check(Manager.HasRollback(false),"persistent rollback created");
                Check(Manager.Run("enable",root,log)==0,"enable idempotent");
                Check(Manager.Run("rollback",root,log)==0,"rollback first install");
                int behavior;Check(Manager.Registration(RegistryView.Registry64,out behavior)==null,"rollback returns disabled");
                Check(Manager.Run("enable",root,log)==0,"enable after rollback");
                // Recreate the three-key journal used before the task-pane class was added.
                foreach(var view in Manager.Views)using(var registry=RegistryKey.OpenBaseKey(RegistryHive.CurrentUser,view)) {
                    registry.DeleteSubKeyTree(@"Software\Classes\CLSID\"+Manager.PaneClassId,false);
                    registry.DeleteSubKeyTree(@"Software\Classes\"+Manager.PaneProgId,false);
                }
                using(var journal=user.OpenSubKey(@"Software\SlidePilot\Deployment",true)) {
                    journal.SetValue("Format",2);journal.DeleteValue("KeyCount",false);
                    foreach(var view in Manager.Views)foreach(int index in new[]{3,4})journal.DeleteSubKeyTree(view+"-"+index,false);
                }
                Check(!Manager.RegistrationComplete(RegistryView.Registry64,root,false),"old release missing AiPane is incomplete");
                Check(Manager.Run("enable",root,log)==0,"upgrade legacy deployment journal");
                Check(Manager.Run("rollback",root,log)==0,"rollback upgrade restores legacy registration");
                Check(Manager.Registration(RegistryView.Registry64,out behavior)==Manager.Codebase(root),"legacy Connect retained by upgrade rollback");
                Check(!Manager.RegistrationComplete(RegistryView.Registry64,root,false),"upgrade rollback removes only new pane");
                Check(Manager.Run("enable",root,log)==0,"enable complete registration after upgrade rollback");
                Check(Manager.Run("disable",root,log)==0,"disable user");
                Check(Manager.Run("disable",root,log)==0,"disable idempotent");
                Check(Manager.Run("rollback",root,log)==0,"rollback repeated disable");
                Check(Manager.Registration(RegistryView.Registry64,out behavior)==Manager.Codebase(root)&&behavior==3,"restored registration");
                string replacement=Path.Combine(Path.GetTempPath(),"SlidePilot-scope-QA-"+Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(replacement);
                try {
                    foreach(string file in Manager.RequiredFiles) {
                        string target=Path.Combine(replacement,file);Directory.CreateDirectory(Path.GetDirectoryName(target));
                        if(file=="SlidePilot.PowerPoint.dll")File.Copy(Path.Combine(root,file),target);else File.WriteAllText(target,"QA placeholder; never executed.");
                    }
                    Check(Manager.Run("enable",replacement,log)==0,"replace old installation");
                    Check(Manager.Run("disable",root,log)==1,"old folder cannot disable replacement");
                    Check(Manager.Run("rollback",root,log)==1,"wrong folder cannot consume rollback");
                    foreach(var view in Manager.Views)using(var registry=RegistryKey.OpenBaseKey(RegistryHive.CurrentUser,view))
                        using(var key=registry.OpenSubKey(@"Software\Microsoft\Office\PowerPoint\Addins\SlidePilot.PowerPoint",true))key.SetValue("LoadBehavior",2,RegistryValueKind.DWord);
                    Check(Manager.Run("rollback",replacement,log)==0,"rollback tolerates Office load failure");
                    Check(Manager.Registration(RegistryView.Registry64,out behavior)==Manager.Codebase(root),"replacement rollback restores old folder");
                } finally {Directory.Delete(replacement,true);}
                Check(Manager.Run("status",root,log,true)==0,"machine status read");
                Check(Manager.Run("enable",root,log,false,true)==2,"replacement unavailable in user scope");
                string server=@"Software\Classes\CLSID\"+Manager.ClassId+@"\InprocServer32";
                using(var key=user.CreateSubKey(server))key.SetValue("Class","Another.Component");
                Check(Manager.Run("enable",root,log)==1,"foreign CLSID is never overwritten");
                using(var key=user.OpenSubKey(server))Check((string)key.GetValue("Class")=="Another.Component","foreign class preserved");
                using(var key=user.CreateSubKey(server))key.SetValue("Class","SlidePilot.Connect");
                string paneServer=@"Software\Classes\CLSID\"+Manager.PaneClassId+@"\InprocServer32";
                using(var key=user.CreateSubKey(paneServer))key.SetValue("Class","Another.Component");
                Check(Manager.Run("enable",root,log)==1,"foreign pane CLSID is never overwritten");
                using(var key=user.CreateSubKey(paneServer)){key.SetValue("Class","SlidePilot.AiPane");key.SetValue("CodeBase",Manager.Codebase(Path.Combine(root,"other")));}
                Check(Manager.Run("disable",root,log)==1,"disable protects pane registered by a different folder");
                using(var key=user.CreateSubKey(paneServer))key.SetValue("CodeBase",Manager.Codebase(root));
                using(var key=machine.CreateSubKey(server)){key.SetValue("Class","SlidePilot.Connect");key.SetValue("CodeBase",Manager.Codebase(root));}
                Check(Manager.HasOtherScope(false),"detect machine conflict from user scope");
                Check(Manager.Run("enable",root,log)==1,"user enable rejects machine conflict");
                machine.DeleteSubKeyTree(@"Software\Classes\CLSID\"+Manager.ClassId,false);
                if(Manager.IsAdministrator()) {
                    Check(Manager.Run("enable",root,log,true)==1,"machine enable rejects user conflict without explicit replacement");
                    Check(Manager.Run("enable",root,log,true,true)==0,"explicit machine replacement");
                    Check(!Manager.HasUserOverride(),"replacement clears current-account registration");
                    Check(Manager.Registration(RegistryView.Registry64,out behavior,true)==Manager.Codebase(root),"machine codebase");
                    Check(Manager.Run("enable",root,log)==1,"user enable does not shadow machine install");
                    Check(Manager.Run("enable",root,log,true,true)==0,"machine replacement idempotent");
                    using(var key=machine.OpenSubKey(@"Software\SlidePilot\Deployment",true))key.SetValue("UserSid","S-1-5-21-1-2-3-1234");
                    Check(Manager.Run("rollback",root,log,true)==1,"wrong account cannot restore migration");
                    using(var key=machine.OpenSubKey(@"Software\SlidePilot\Deployment",true))using(var identity=WindowsIdentity.GetCurrent())key.SetValue("UserSid",identity.User.Value);
                    using(var key=user.CreateSubKey(server)){key.SetValue("Class","SlidePilot.Connect");key.SetValue("CodeBase",Manager.Codebase(root));}
                    Check(Manager.Run("rollback",root,log,true)==1,"migration rollback rejects later user registration");
                    user.DeleteSubKeyTree(@"Software\Classes\CLSID\"+Manager.ClassId,false);
                    Check(Manager.Run("rollback",root,log,true)==0,"machine migration rollback");
                    Check(Manager.Registration(RegistryView.Registry64,out behavior,true)==null,"machine rollback removes new machine registration");
                    Check(Manager.Registration(RegistryView.Registry64,out behavior)==Manager.Codebase(root),"machine rollback restores original user registration");
                } else Check(Manager.Run("enable",root,log,true)==1,"machine non-admin denied");
                using(var key=user.OpenSubKey(neighbor))Check((string)key.GetValue("Marker")=="keep","PagePilot user preserved");
                using(var key=machine.OpenSubKey(neighbor))Check((string)key.GetValue("Marker")=="keep-machine","PagePilot machine preserved");
                Check(Manager.Run("enable",root,log)==0,"prepare changed-registration test");
                using(var key=user.CreateSubKey(@"Software\Microsoft\Office\PowerPoint\Addins\SlidePilot.PowerPoint"))key.SetValue("Unexpected","external");
                Check(Manager.Run("rollback",root,log)==1,"reject external change");
                using(var key=user.OpenSubKey(@"Software\Microsoft\Office\PowerPoint\Addins\SlidePilot.PowerPoint"))Check((string)key.GetValue("Unexpected")=="external","external marker preserved");
                Check(Manager.Run("enable",root,log)==0,"repair externally changed registration");
                Check(Manager.Run("rollback",root,log)==0,"repair creates compatible fresh backup");
                using(var key=user.OpenSubKey(@"Software\Microsoft\Office\PowerPoint\Addins\SlidePilot.PowerPoint"))Check((string)key.GetValue("Unexpected")=="external","repair rollback restores external marker");
                Check(Manager.Run("enable",root,log)==0,"prepare interrupted journal test");
                using(var key=user.OpenSubKey(@"Software\SlidePilot\Deployment",true))key.SetValue("State","pending");
                Check(!Manager.HasRollback(false),"incomplete journal is not advertised as rollback");
                Check(Manager.Run("disable",root,log)==1,"pending journal blocks new writes");
                Check(Manager.Registration(RegistryView.Registry64,out behavior)==Manager.Codebase(root),"pending refusal leaves registration intact");
                return 0;
            } finally {
                if(redirectedUser)RegOverridePredefKey(hkcu,IntPtr.Zero);if(redirectedMachine)RegOverridePredefKey(hklm,IntPtr.Zero);
                realUser.DeleteSubKeyTree(temporary,false);
            }
        }
    }
}
