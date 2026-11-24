using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using Microsoft.Win32;

namespace SlidePilot {
    public static class Manager {
        public const string ProgId="SlidePilot.PowerPoint";
        public const string ClassId="{FB9007D1-2CB9-4C9D-8FC4-4A96CA980A3E}";
        const string Classes=@"Software\Classes\";
        const string Addins=@"Software\Microsoft\Office\PowerPoint\Addins\";
        static readonly string[] Keys={Classes+@"CLSID\"+ClassId,Classes+ProgId,Addins+ProgId};
        static readonly RegistryView[] Views=Environment.Is64BitOperatingSystem ?
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
        }
        static string Codebase(string dir) {return new Uri(Path.Combine(dir,"SlidePilot.PowerPoint.dll")).AbsoluteUri;}
        static void Enable(RegistryKey baseKey,string dir) {
            string dll=Path.Combine(dir,"SlidePilot.PowerPoint.dll");
            var ass=AssemblyName.GetAssemblyName(dll);
            using(var cls=baseKey.CreateSubKey(Keys[0])) {
                cls.SetValue("","SlidePilot for PowerPoint");
                using(var id=cls.CreateSubKey("ProgId")) id.SetValue("",ProgId);
                using(var server=cls.CreateSubKey("InprocServer32")) {
                    server.SetValue("","mscoree.dll");
                    server.SetValue("ThreadingModel","Both");
                    using(var version=server.CreateSubKey(ass.Version.ToString())) foreach(var k in new[]{server,version}) {
                        k.SetValue("Class","SlidePilot.Connect"); k.SetValue("Assembly",ass.FullName);
                        k.SetValue("RuntimeVersion","v4.0.30319"); k.SetValue("CodeBase",Codebase(dir));
                    }
                }
            }
            using(var p=baseKey.CreateSubKey(Keys[1]+@"\CLSID")) p.SetValue("",ClassId);
            using(var a=baseKey.CreateSubKey(Keys[2])) {
                a.SetValue("LoadBehavior",3,RegistryValueKind.DWord); a.SetValue("FriendlyName","SlidePilot");
                a.SetValue("Description","SlidePilot presentation assistant"); a.SetValue("CommandLineSafe",0,RegistryValueKind.DWord);
            }
        }
        public static int Main(string[] args) {
            if(args.Length!=1 || Array.IndexOf(new[]{"enable","disable","status"},args[0])<0) {Console.Error.WriteLine("SlidePilot.Manager.exe enable | disable | status");return 2;}
            string dir=AppDomain.CurrentDomain.BaseDirectory;
            var history=new Stack<Action>();
            bool owned=false;
            using(var mutex=new System.Threading.Mutex(false,@"Local\SlidePilot.PowerPoint.Deployment")) try {
                try {owned=mutex.WaitOne(10000);} catch(System.Threading.AbandonedMutexException){owned=true;}
                if(!owned) throw new IOException("Another SlidePilot deployment is active.");
                if(args[0]=="enable") foreach(var f in new[]{"SlidePilot.PowerPoint.dll","SlidePilot.Validate.exe","DocumentFormat.OpenXml.dll",@"Electron\electron.exe",@"Runtime\python.exe",@"Chatbox\bootstrap.cjs",@"Chatbox\dist\renderer\index.html",@"engine\server.py",@"assets\chart-members.json"})
                    if(!File.Exists(Path.Combine(dir,f))) throw new FileNotFoundException("Extract the complete portable archive.",f);
                foreach(var view in Views) using(var reg=RegistryKey.OpenBaseKey(RegistryHive.CurrentUser,view)) {
                    string existing;
                    using(var k=reg.OpenSubKey(Keys[0]+@"\InprocServer32")) existing=k==null?null:k.GetValue("CodeBase") as string;
                    if(args[0]=="status") {Console.WriteLine(view+"  "+(existing??"(disabled)")); continue;}
                    if(args[0]=="disable" && existing!=null && !String.Equals(existing,Codebase(dir),StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException("A different SlidePilot location is registered. Disable it from that folder.");
                    foreach(string path in Keys) {
                        Snapshot snapshot;
                        using(var k=reg.OpenSubKey(path)) snapshot=Snapshot.Read(k);
                        var capturedView=view; var capturedPath=path; var captured=snapshot;
                        history.Push(delegate {using(var hive=RegistryKey.OpenBaseKey(RegistryHive.CurrentUser,capturedView)) {
                            hive.DeleteSubKeyTree(capturedPath,false);
                            if(captured!=null) using(var k=hive.CreateSubKey(capturedPath)) captured.Restore(k);
                        }});
                    }
                    if(args[0]=="enable") Enable(reg,dir);
                    else foreach(string path in Keys) reg.DeleteSubKeyTree(path,false);
                }
                if(args[0]!="status") Console.WriteLine("SlidePilot "+args[0]+" completed. Reopen PowerPoint.");
                return 0;
            } catch(Exception e) {
                Console.Error.WriteLine(e.Message);
                while(history.Count>0) try {history.Pop()();} catch(Exception rollback) {Console.Error.WriteLine("Rollback: "+rollback.Message);}
                return 1;
            } finally {if(owned) mutex.ReleaseMutex();}
        }
    }
}
