using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Diagnostics;
using System.Security.Principal;
using System.Security.AccessControl;
using Microsoft.Win32;

namespace SlidePilot {
    public static class Manager {
        public const string ProgId="SlidePilot.PowerPoint";
        public const string ClassId="{FB9007D1-2CB9-4C9D-8FC4-4A96CA980A3E}";
        const string Classes=@"Software\Classes\";
        const string Addins=@"Software\Microsoft\Office\PowerPoint\Addins\";
        const string Deployment=@"Software\SlidePilot\Deployment";
        static readonly string[] Keys={Classes+@"CLSID\"+ClassId,Classes+ProgId,Addins+ProgId};
        public static readonly RegistryView[] Views=Environment.Is64BitOperatingSystem ?
            new[]{RegistryView.Registry32,RegistryView.Registry64}:new[]{RegistryView.Registry32};
        class Snapshot {
            public Dictionary<string,object> Values=new Dictionary<string,object>();
            public Dictionary<string,RegistryValueKind> Kinds=new Dictionary<string,RegistryValueKind>();
            public Dictionary<string,Snapshot> Children=new Dictionary<string,Snapshot>();
            public static Snapshot Read(RegistryKey key) {
                if(key==null) return null;
                var s=new Snapshot();
                foreach(string n in key.GetValueNames()) {s.Values[n]=key.GetValue(n,null,RegistryValueOptions.DoNotExpandEnvironmentNames);s.Kinds[n]=key.GetValueKind(n);}
                foreach(string n in key.GetSubKeyNames()) using(var sub=key.OpenSubKey(n)) s.Children[n]=Read(sub);
                return s;
            }
            public void Restore(RegistryKey key) {
                foreach(var v in Values) key.SetValue(v.Key,v.Value,Kinds[v.Key]);
                foreach(var c in Children) using(var sub=key.CreateSubKey(c.Key)) c.Value.Restore(sub);
            }
            public bool Same(Snapshot other,bool loadBehaviorMayFail) {
                if(other==null || Values.Count!=other.Values.Count || Children.Count!=other.Children.Count) return false;
                foreach(var pair in Values) {
                    object value;
                    if(!other.Values.TryGetValue(pair.Key,out value) || Kinds[pair.Key]!=other.Kinds[pair.Key]) return false;
                    if(loadBehaviorMayFail && pair.Key=="LoadBehavior" && Convert.ToInt32(pair.Value)==3 && Convert.ToInt32(value)==2) continue;
                    if(!ValueEquals(pair.Value,value)) return false;
                }
                foreach(var pair in Children) {
                    Snapshot child;
                    if(!other.Children.TryGetValue(pair.Key,out child) || !pair.Value.Same(child,false)) return false;
                }
                return true;
            }
            static bool ValueEquals(object left,object right) {
                var a=left as Array;var b=right as Array;
                if(a==null || b==null)return Object.Equals(left,right);
                if(a.Length!=b.Length)return false;
                for(int i=0;i<a.Length;i++)if(!Object.Equals(a.GetValue(i),b.GetValue(i)))return false;
                return true;
            }
        }
        class Entry {
            public RegistryView View;
            public int Index;
            public Snapshot Before,After;
        }
        static RegistryHive Hive(bool machine) {return machine?RegistryHive.LocalMachine:RegistryHive.CurrentUser;}
        static RegistryView JournalView {get{return Environment.Is64BitOperatingSystem?RegistryView.Registry64:RegistryView.Registry32;}}
        public static bool IsAdministrator() {
            using(var id=WindowsIdentity.GetCurrent())return new WindowsPrincipal(id).IsInRole(WindowsBuiltInRole.Administrator);
        }
        public static bool HasUserOverride() {
            return HasRegistration(false);
        }
        public static bool HasOtherScope(bool machine) {return HasRegistration(!machine);}
        static bool HasRegistration(bool machine) {
            foreach(var view in Views)using(var reg=RegistryKey.OpenBaseKey(Hive(machine),view))
                foreach(string path in Keys)using(var key=reg.OpenSubKey(path))if(key!=null)return true;
            return false;
        }
        public static bool HasRollback(bool machine) {
            try {string state,target;ReadJournal(machine,out state,out target);return state=="complete";}
            catch(IOException){return false;}
            catch(InvalidOperationException){return false;}
        }
        // Match RegAsm's CodeBase representation, including literal spaces in local paths.
        public static string Codebase(string dir) {return new Uri(Path.Combine(Path.GetFullPath(dir),"SlidePilot.PowerPoint.dll")).ToString();}
        public static bool SameCodebase(string left,string right) {
            Uri a,b;
            if(String.IsNullOrWhiteSpace(left) || String.IsNullOrWhiteSpace(right) ||
               !Uri.TryCreate(left,UriKind.Absolute,out a) || !Uri.TryCreate(right,UriKind.Absolute,out b) ||
               !a.IsFile || !b.IsFile || a.Query.Length!=0 || b.Query.Length!=0 || a.Fragment.Length!=0 || b.Fragment.Length!=0)return false;
            try{return String.Equals(Path.GetFullPath(a.LocalPath),Path.GetFullPath(b.LocalPath),StringComparison.OrdinalIgnoreCase);}
            catch(ArgumentException){return false;}catch(NotSupportedException){return false;}catch(PathTooLongException){return false;}
        }
        public static readonly string[] RequiredFiles={"SlidePilot.PowerPoint.dll","SlidePilot.Validate.exe","DocumentFormat.OpenXml.dll",@"Electron\electron.exe",@"Runtime\python.exe",@"Chatbox\bootstrap.cjs",@"Chatbox\dist\main\main.js",@"Chatbox\dist\renderer\index.html",@"Chatbox\workspace-main.cjs",@"Chatbox\settings-entry.cjs",@"Chatbox\settings-preload.cjs",@"Chatbox\settings.html",@"Chatbox\settings.css",@"Chatbox\settings.js",@"engine\server.py",@"engine\reference_server.py",@"engine\reference_files.py",@"assets\chart-members.json"};
        public static string[] MissingFiles(string dir) {
            var missing=new List<string>();
            foreach(string file in RequiredFiles) if(!File.Exists(Path.Combine(dir,file))) missing.Add(file);
            return missing.ToArray();
        }
        public static string MachinePathWarning(string dir) {
            string target=Path.GetFullPath(dir);
            const FileSystemRights writes=FileSystemRights.Write|FileSystemRights.Delete|FileSystemRights.DeleteSubdirectoriesAndFiles|FileSystemRights.ChangePermissions|FileSystemRights.TakeOwnership;
            var administrators=new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid,null);
            var system=new SecurityIdentifier(WellKnownSidType.LocalSystemSid,null);
            try {
                var paths=new List<string>{target};foreach(string file in RequiredFiles)paths.Add(Path.Combine(target,file));
                foreach(string path in paths) {
                    bool directory=Directory.Exists(path);if(!directory && !File.Exists(path))continue;
                    if((File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0)return "All-users code path contains a link/reparse point: "+path+". Use a fixed administrator-controlled folder.";
                    FileSystemSecurity security=directory?(FileSystemSecurity)new DirectoryInfo(path).GetAccessControl():new FileInfo(path).GetAccessControl();
                    foreach(FileSystemAccessRule rule in security.GetAccessRules(true,true,typeof(SecurityIdentifier))) {
                        var sid=(SecurityIdentifier)rule.IdentityReference;
                        if(rule.AccessControlType==AccessControlType.Allow && (rule.FileSystemRights&writes)!=0 && !sid.Equals(administrators) && !sid.Equals(system) && sid.Value!="S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464")
                            return "All-users code path has a write-access grant outside Administrators/SYSTEM: "+path+" ("+sid.Value+"). Use a fixed folder protected from ordinary-account writes; this installer does not change folder permissions.";
                    }
                }
                return "All-users registration shares this code folder. Keep the entire portable folder administrator-controlled and readable by its users; registration does not secure file permissions.";
            } catch(Exception e){return "Could not verify shared code-folder permissions: "+e.Message+". Use an administrator-controlled fixed folder.";}
        }
        public static string OfficePath(string executable) {
            foreach(var hive in new[]{RegistryHive.CurrentUser,RegistryHive.LocalMachine}) foreach(var view in Views)
                using(var reg=RegistryKey.OpenBaseKey(hive,view))
                using(var key=reg.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\App Paths\"+executable)) {
                    string value=key==null?null:key.GetValue("") as string;
                    if(!String.IsNullOrWhiteSpace(value) && File.Exists(value.Trim('"'))) return value.Trim('"');
                }
            return null;
        }
        public static string Registration(RegistryView view,out int behavior) {
            return Registration(view,out behavior,false);
        }
        public static string Registration(RegistryView view,out int behavior,bool machine) {
            using(var reg=RegistryKey.OpenBaseKey(Hive(machine),view)) {
                using(var k=reg.OpenSubKey(Keys[2])) {var value=k==null?null:k.GetValue("LoadBehavior");behavior=value is int?(int)value:-1;}
                using(var k=reg.OpenSubKey(Keys[0]+@"\InprocServer32")) return k==null?null:k.GetValue("CodeBase") as string;
            }
        }
        static void Enable(RegistryKey baseKey,string dir) {
            string dll=Path.Combine(dir,"SlidePilot.PowerPoint.dll");
            var ass=AssemblyName.GetAssemblyName(dll);
            using(var cls=baseKey.CreateSubKey(Keys[0])) {
                cls.SetValue("","SlidePilot.Connect");
                using(var id=cls.CreateSubKey("ProgId")) id.SetValue("",ProgId);
                using(var category=cls.CreateSubKey(@"Implemented Categories\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}")) {}
                using(var server=cls.CreateSubKey("InprocServer32")) {
                    server.SetValue("","mscoree.dll");
                    server.SetValue("ThreadingModel","Both");
                    using(var version=server.CreateSubKey(ass.Version.ToString())) foreach(var k in new[]{server,version}) {
                        k.SetValue("Class","SlidePilot.Connect"); k.SetValue("Assembly",ass.FullName);
                        k.SetValue("RuntimeVersion","v4.0.30319"); k.SetValue("CodeBase",Codebase(dir));
                    }
                }
            }
            using(var p=baseKey.CreateSubKey(Keys[1])) {
                p.SetValue("","SlidePilot.Connect");
                using(var clsid=p.CreateSubKey("CLSID"))clsid.SetValue("",ClassId);
            }
            using(var a=baseKey.CreateSubKey(Keys[2])) {
                a.SetValue("LoadBehavior",3,RegistryValueKind.DWord); a.SetValue("FriendlyName","SlidePilot");
                a.SetValue("Description","SlidePilot presentation assistant"); a.SetValue("CommandLineSafe",0,RegistryValueKind.DWord);
            }
        }
        public static int Main(string[] args) {
            if(args.Length==1 && args[0]=="check-package") {
                var missing=MissingFiles(AppDomain.CurrentDomain.BaseDirectory);
                if(missing.Length>0){Console.Error.WriteLine("Incomplete package: "+String.Join(", ",missing));return 1;}
                Console.WriteLine("Portable package entry points present.");
                return 0;
            }
            bool machine=false,replace=false,valid=args.Length>0 && Array.IndexOf(new[]{"enable","disable","status","rollback"},args[0])>=0;
            for(int i=1;i<args.Length;i++) {
                if(args[i]=="--machine" && !machine)machine=true;
                else if(args[i]=="--replace-existing" && !replace)replace=true;
                else valid=false;
            }
            if(!valid){Console.Error.WriteLine("SlidePilot.Manager.exe enable | disable | status | rollback [--machine] [--replace-existing]");return 2;}
            try{return Run(args[0],AppDomain.CurrentDomain.BaseDirectory,Console.Out,machine,replace);}
            catch(Exception e){Console.Error.WriteLine(e.Message);return 1;}
        }
        public static int Run(string verb,string dir,TextWriter output) {return Run(verb,dir,output,false);}
        static List<Entry> Capture(bool machine) {
            var result=new List<Entry>();
            foreach(var view in Views)using(var reg=RegistryKey.OpenBaseKey(Hive(machine),view))
                for(int index=0;index<Keys.Length;index++)using(var key=reg.OpenSubKey(Keys[index]))result.Add(new Entry{View=view,Index=index,Before=Snapshot.Read(key)});
            return result;
        }
        static void RestoreEntries(bool machine,List<Entry> entries) {
            // Each target is selected from the three owned registration keys, never from backup data.
            foreach(var entry in entries)using(var reg=RegistryKey.OpenBaseKey(Hive(machine),entry.View)) {
                reg.DeleteSubKeyTree(Keys[entry.Index],false);
                if(entry.Before!=null)using(var key=reg.CreateSubKey(Keys[entry.Index]))entry.Before.Restore(key);
                using(var key=reg.OpenSubKey(Keys[entry.Index])) {
                    var actual=Snapshot.Read(key);
                    if(entry.Before==null?actual!=null:!entry.Before.Same(actual,false))throw new IOException("Registry recovery read-back failed: "+Keys[entry.Index]);
                }
            }
        }
        static void CheckOwnership(bool machine) {
            foreach(var view in Views)using(var reg=RegistryKey.OpenBaseKey(Hive(machine),view)) {
                using(var key=reg.OpenSubKey(Keys[0]+@"\InprocServer32")) {
                    string cls=key==null?null:Convert.ToString(key.GetValue("Class"));
                    if(!String.IsNullOrEmpty(cls) && cls!="SlidePilot.Connect")throw new IOException("SlidePilot CLSID belongs to another component. No registration will be replaced.");
                }
                using(var key=reg.OpenSubKey(Keys[1]+@"\CLSID")) {
                    string id=key==null?null:Convert.ToString(key.GetValue(""));
                    if(!String.IsNullOrEmpty(id) && !String.Equals(id,ClassId,StringComparison.OrdinalIgnoreCase))throw new IOException("SlidePilot ProgID points to another component. No registration will be replaced.");
                }
                using(var key=reg.OpenSubKey(Keys[2])) {
                    string name=key==null?null:Convert.ToString(key.GetValue("FriendlyName"));
                    if(!String.IsNullOrEmpty(name) && name!="SlidePilot")throw new IOException("The PowerPoint add-in registration belongs to another component.");
                }
            }
        }
        static string UserSid() {using(var user=WindowsIdentity.GetCurrent())return user.User.Value;}
        static void ValidateMigrationOwner(List<Entry> migrated,string sid) {
            if(migrated!=null && sid!=UserSid())throw new InvalidOperationException("This rollback includes another Windows account's per-user registration. Run it as the same account that performed the replacement.");
        }
        static string EntryName(Entry entry) {return entry.View.ToString()+"-"+entry.Index;}
        static void WriteSnapshot(RegistryKey key,string name,Snapshot snapshot) {
            key.SetValue(name+"Exists",snapshot==null?0:1,RegistryValueKind.DWord);
            if(snapshot!=null)using(var child=key.CreateSubKey(name))snapshot.Restore(child);
        }
        static Snapshot ReadSnapshot(RegistryKey key,string name) {
            object marker=key.GetValue(name+"Exists");
            if(!(marker is int) || ((int)marker!=0 && (int)marker!=1))throw new IOException("Incomplete deployment backup: missing "+name+"Exists marker.");
            if((int)marker==0)return null;
            using(var child=key.OpenSubKey(name)) {
                if(child==null)throw new IOException("Incomplete deployment backup: "+name);
                return Snapshot.Read(child);
            }
        }
        static void SaveJournal(bool machine,List<Entry> entries,string dir,string state,List<Entry> migrated) {
            using(var reg=RegistryKey.OpenBaseKey(Hive(machine),JournalView)) {
                // Completing a transaction keeps the already-flushed recovery snapshot intact.
                if(state!="complete")reg.DeleteSubKeyTree(Deployment,false);
                using(var journal=reg.CreateSubKey(Deployment)) {
                    if(state!="complete") {
                        journal.SetValue("Format",2,RegistryValueKind.DWord);journal.SetValue("State",state);journal.SetValue("Target",Codebase(dir));
                        journal.SetValue("CreatedUtc",DateTime.UtcNow.ToString("o"));
                        journal.SetValue("MachineScope",machine?1:0,RegistryValueKind.DWord);
                        journal.SetValue("MigratedUser",migrated==null?0:1,RegistryValueKind.DWord);
                        if(migrated!=null)journal.SetValue("UserSid",UserSid());
                    }
                    foreach(var entry in entries)using(var key=journal.CreateSubKey(EntryName(entry))) {
                        if(state!="complete")WriteSnapshot(key,"Before",entry.Before);
                        WriteSnapshot(key,"After",entry.After);
                    }
                    if(migrated!=null)using(var users=journal.CreateSubKey("UserEntries"))foreach(var entry in migrated)
                        using(var key=users.CreateSubKey(EntryName(entry))) {
                            if(state!="complete")WriteSnapshot(key,"Before",entry.Before);
                            WriteSnapshot(key,"After",entry.After);
                        }
                    journal.Flush();
                    journal.SetValue("State",state);
                    journal.Flush();
                }
            }
        }
        static List<Entry> ReadJournal(bool machine,out string state,out string target) {
            List<Entry> migrated;string sid;
            return ReadJournal(machine,out state,out target,out migrated,out sid);
        }
        static List<Entry> ReadJournal(bool machine,out string state,out string target,out List<Entry> migrated,out string sid) {
            var entries=new List<Entry>();
            migrated=null;sid=null;
            using(var reg=RegistryKey.OpenBaseKey(Hive(machine),JournalView))using(var journal=reg.OpenSubKey(Deployment)) {
                int format=journal==null?0:Convert.ToInt32(journal.GetValue("Format",0));
                if(format!=1 && format!=2)throw new InvalidOperationException("No SlidePilot rollback point is available for this scope.");
                if(format==2 && Convert.ToInt32(journal.GetValue("MachineScope",-1))!=(machine?1:0))throw new IOException("Deployment backup scope does not match this operation.");
                state=journal.GetValue("State","") as string;target=journal.GetValue("Target","") as string;
                entries=ReadEntries(journal);
                if(format==2) {
                    int marker=Convert.ToInt32(journal.GetValue("MigratedUser",-1));
                    if(marker!=0 && marker!=1)throw new IOException("Invalid user migration marker in deployment backup.");
                    if(marker==1) {
                        sid=journal.GetValue("UserSid") as string;
                        if(!machine || String.IsNullOrEmpty(sid))throw new IOException("Invalid user migration scope in deployment backup.");
                        using(var users=journal.OpenSubKey("UserEntries")) {
                            if(users==null)throw new IOException("The user migration backup is incomplete.");
                            migrated=ReadEntries(users);
                        }
                        if(migrated.Exists(entry=>entry.After!=null))throw new IOException("Invalid migration result in deployment backup.");
                    }
                }
            }
            return entries;
        }
        static List<Entry> ReadEntries(RegistryKey journal) {
            var entries=new List<Entry>();
            foreach(var view in Views)for(int index=0;index<Keys.Length;index++) {
                var entry=new Entry{View=view,Index=index};
                using(var key=journal.OpenSubKey(EntryName(entry))) {
                    if(key==null)throw new IOException("Incomplete deployment backup. No registry changes were made.");
                    entry.Before=ReadSnapshot(key,"Before");entry.After=ReadSnapshot(key,"After");
                }
                entries.Add(entry);
            }
            return entries;
        }
        static void ArchiveJournal(bool machine,Snapshot previous,TextWriter output) {
            if(previous==null)return;
            string path=Deployment+"History\\"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fffffff")+"-"+Guid.NewGuid().ToString("N");
            using(var registry=RegistryKey.OpenBaseKey(Hive(machine),JournalView))using(var key=registry.CreateSubKey(path)){previous.Restore(key);key.Flush();}
            output.WriteLine("Previous deployment backup archived: "+(machine?"HKLM":"HKCU")+@"\"+path);
        }
        static void ValidateOldDll(List<Entry> entries) {
            foreach(var entry in entries)if(entry.Index==0 && entry.Before!=null) {
                Snapshot server;object value;
                if(entry.Before.Children.TryGetValue("InprocServer32",out server) && server.Values.TryGetValue("CodeBase",out value)) {
                    Uri uri;
                    if(!Uri.TryCreate(value as string,UriKind.Absolute,out uri) || !uri.IsFile || !File.Exists(uri.LocalPath))throw new FileNotFoundException("The previous SlidePilot DLL is missing. Restore its folder before rolling back.");
                }
            }
        }
        static bool MatchesJournal(bool machine,List<Entry> actual,string dir) {
            string state,target,sid;List<Entry> previous,migrated;
            try{previous=ReadJournal(machine,out state,out target,out migrated,out sid);}catch(IOException){return false;}catch(InvalidOperationException){return false;}
            if(state!="complete" || !SameCodebase(target,Codebase(dir)))return false;
            // Preserving a prior rollback point does not restore its user's registry.
            // SID ownership is required only when rollback consumes that migration.
            if(migrated!=null && HasUserOverride())return false;
            for(int i=0;i<previous.Count;i++) {
                var expected=previous[i].After;var value=actual[i].Before;
                if(expected==null?value!=null:!expected.Same(value,previous[i].Index==2))return false;
            }
            return true;
        }
        public static int Run(string verb,string dir,TextWriter output,bool machine) {
            return Run(verb,dir,output,machine,false);
        }
        public static int Run(string verb,string dir,TextWriter output,bool machine,bool replaceExisting) {
            if(Array.IndexOf(new[]{"enable","disable","status","rollback"},verb)<0) {output.WriteLine("Unknown operation.");return 2;}
            if(replaceExisting && (!machine || verb!="enable")){output.WriteLine("Replacing old registrations is only available for all-users enable.");return 2;}
            List<Entry> history=null,historyUser=null;Snapshot journalBefore=null;bool journalTouched=false,changed=false,owned=false;
            using(var mutex=new System.Threading.Mutex(false,@"Global\SlidePilot.PowerPoint.Deployment")) try {
                dir=Path.GetFullPath(dir);
                try {owned=mutex.WaitOne(10000);} catch(System.Threading.AbandonedMutexException){owned=true;}
                if(!owned) throw new IOException("Another SlidePilot deployment is active.");
                output.WriteLine("Scope: "+(machine?"all users (HKLM)":"current user (HKCU)"));
                if(machine)output.WriteLine(MachinePathWarning(dir));
                if(verb!="status" && machine && !IsAdministrator())throw new UnauthorizedAccessException("All-users installation requires administrator rights. Reopen SlidePilot.Setup.exe and choose All users to request elevation.");
                if(verb=="status") {
                    foreach(var view in Views) {int behavior;string existing=Registration(view,out behavior,machine);output.WriteLine(view+"  "+(existing??"(disabled)")+"  LoadBehavior="+behavior);}
                    output.WriteLine("Rollback available: "+HasRollback(machine));
                    if(machine && HasUserOverride())output.WriteLine("WARNING: A current-user SlidePilot registration can override the all-users registration. Disable that registration in Current user mode first. Other accounts keep their own overrides.");
                    return 0;
                }
                if(verb=="enable") {
                    var missing=MissingFiles(dir);
                    if(missing.Length>0)throw new FileNotFoundException("Extract the complete portable archive. Missing: "+String.Join(", ",missing));
                    if(AssemblyName.GetAssemblyName(Path.Combine(dir,"SlidePilot.PowerPoint.dll")).Name!="SlidePilot.PowerPoint")throw new InvalidDataException("The add-in assembly identity does not match SlidePilot.PowerPoint.");
                    if(!replaceExisting && HasOtherScope(machine))throw new InvalidOperationException("SlidePilot is registered in the other scope. Select All users and Replace old registrations to back up and migrate the current account, or disable the other scope first.");
                }
                CheckOwnership(machine);
                if(replaceExisting)CheckOwnership(false);
                bool sameLocation=true;
                foreach(var view in Views) {
                    int behavior;string existing=Registration(view,out behavior,machine);
                    sameLocation &= SameCodebase(existing,Codebase(dir));
                    if(verb=="disable" && existing!=null && !SameCodebase(existing,Codebase(dir)))throw new InvalidOperationException("A different SlidePilot location is registered. Disable it from that folder.");
                }
                using(var reg=RegistryKey.OpenBaseKey(Hive(machine),JournalView))using(var key=reg.OpenSubKey(Deployment))journalBefore=Snapshot.Read(key);
                history=Capture(machine);
                if(replaceExisting) {historyUser=Capture(false);if(!historyUser.Exists(entry=>entry.Before!=null))historyUser=null;}
                if(verb=="rollback") {
                    string state,target,sid;List<Entry> previousUser;var previous=ReadJournal(machine,out state,out target,out previousUser,out sid);
                    if(state!="complete")throw new InvalidOperationException("An interrupted deployment needs manual recovery from "+(machine?"HKLM":"HKCU")+@"\"+Deployment+". The saved Before snapshots are preserved; no registration changes were made.");
                    if(!SameCodebase(target,Codebase(dir)))throw new InvalidOperationException("Run rollback from the folder that created this rollback point.");
                    ValidateMigrationOwner(previousUser,sid);
                    ValidateOldDll(previous);
                    if(previousUser!=null) {
                        ValidateOldDll(previousUser);CheckOwnership(false);historyUser=Capture(false);
                        if(historyUser.Exists(entry=>entry.Before!=null))throw new InvalidOperationException("The current account's SlidePilot registration changed after replacement. Rollback stopped to protect it.");
                    } else if(previous.Exists(entry=>entry.Before!=null) && HasOtherScope(machine))throw new InvalidOperationException("Restoring this version would conflict with SlidePilot in the other scope. Disable that registration first.");
                    for(int i=0;i<previous.Count;i++) {
                        var expected=previous[i].After;var actual=history[i].Before;
                        if(expected==null?actual!=null:!expected.Same(actual,previous[i].Index==2))throw new InvalidOperationException("SlidePilot registration changed after deployment. Rollback stopped to protect the newer registration.");
                    }
                    changed=true;RestoreEntries(machine,previous);
                    if(previousUser!=null)RestoreEntries(false,previousUser);
                    journalTouched=true;using(var reg=RegistryKey.OpenBaseKey(Hive(machine),JournalView))reg.DeleteSubKeyTree(Deployment,false);
                } else {
                    // Re-enabling the same folder retains its earlier version rollback point.
                    bool savePoint=verb=="enable"? !sameLocation || journalBefore==null || historyUser!=null : history.Exists(entry=>entry.Before!=null) || journalBefore==null;
                    if(journalBefore!=null) {
                        object state;
                        if(journalBefore.Values.TryGetValue("State",out state) && !Object.Equals(state,"complete"))throw new InvalidOperationException("An interrupted deployment backup exists. Recover it before changing registration.");
                    }
                    if(!savePoint && !MatchesJournal(machine,history,dir))savePoint=true;
                    if(savePoint){ArchiveJournal(machine,journalBefore,output);journalTouched=true;SaveJournal(machine,history,dir,"pending",historyUser);}
                    changed=true;
                    if(historyUser!=null) {
                        foreach(var view in Views)using(var reg=RegistryKey.OpenBaseKey(RegistryHive.CurrentUser,view))foreach(string path in Keys)reg.DeleteSubKeyTree(path,false);
                        if(HasUserOverride())throw new IOException("The old per-user registration could not be removed.");
                        output.WriteLine("Backed up and removed current-account registration. SID: "+UserSid());
                    }
                    foreach(var view in Views)using(var reg=RegistryKey.OpenBaseKey(Hive(machine),view)) {
                        if(verb=="enable") {foreach(string path in Keys)reg.DeleteSubKeyTree(path,false);Enable(reg,dir);}
                        else foreach(string path in Keys)reg.DeleteSubKeyTree(path,false);
                    }
                    foreach(var view in Views) {
                        int behavior;string actual=Registration(view,out behavior,machine);
                        if(verb=="enable"? !SameCodebase(actual,Codebase(dir))||behavior!=3 : actual!=null||behavior!=-1)throw new IOException("Registration read-back failed: "+view);
                    }
                    if(savePoint) {var after=Capture(machine);for(int i=0;i<history.Count;i++)history[i].After=after[i].Before;SaveJournal(machine,history,dir,"complete",historyUser);}
                }
                output.WriteLine("SlidePilot "+verb+" completed. Reopen PowerPoint.");
                return 0;
            } catch(Exception e) {
                output.WriteLine(e.Message);
                bool restored=true;
                if(changed && history!=null)try{RestoreEntries(machine,history);}catch(Exception rollback){restored=false;output.WriteLine("Rollback failed; deployment backup is preserved: "+rollback.Message);}
                if(changed && historyUser!=null)try{RestoreEntries(false,historyUser);}catch(Exception rollback){restored=false;output.WriteLine("User registration recovery failed; migration backup is preserved: "+rollback.Message);}
                if(journalTouched && restored)try{using(var reg=RegistryKey.OpenBaseKey(Hive(machine),JournalView)){reg.DeleteSubKeyTree(Deployment,false);if(journalBefore!=null)using(var key=reg.CreateSubKey(Deployment))journalBefore.Restore(key);}}catch(Exception rollback){output.WriteLine("Backup restore: "+rollback.Message);}
                return 1;
            } finally {if(owned) mutex.ReleaseMutex();}
        }
    }
}
