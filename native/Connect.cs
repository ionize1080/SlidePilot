using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Pipes;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using Extensibility;
using Office=Microsoft.Office.Core;

[assembly: AssemblyVersion("0.1.0.0")]
[assembly: AssemblyFileVersion("0.1.0.0")]
[assembly: ComVisible(false)]

namespace SlidePilot {
    [ComVisible(true),Guid("BBF769A9-5878-4B42-BB2F-7BD8D197AE92"),InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
    public interface IRibbon {
        [DispId(1)] void OpenChat(Office.IRibbonControl control);
        [DispId(2)] void SelectWorkspace(Office.IRibbonControl control);
        [DispId(3)] void SetAutomatic(Office.IRibbonControl control,bool pressed);
        [DispId(4)] bool GetAutomatic(Office.IRibbonControl control);
        [DispId(5)] void Loaded(Office.IRibbonUI ribbon);
        [DispId(6)] [return:MarshalAs(UnmanagedType.IDispatch)] object GetImage(Office.IRibbonControl control);
        [DispId(7)] void OpenSettings(Office.IRibbonControl control);
    }
    [ComVisible(true),Guid("FB9007D1-2CB9-4C9D-8FC4-4A96CA980A3E"),ProgId("SlidePilot.PowerPoint"),ClassInterface(ClassInterfaceType.None),ComDefaultInterface(typeof(IRibbon))]
    public sealed class Connect:IDTExtensibility2,Office.IRibbonExtensibility,IRibbon {
        dynamic app;
        Control ui;
        Office.IRibbonUI ribbon;
        Process assistant,settingsProcess;
        IntPtr settingsHandle;
        System.Windows.Forms.Timer timer;
        System.Windows.Forms.Timer launchTimer;
        System.Windows.Forms.Timer settingsLaunchTimer;
        WindowChanged windowChanged;
        volatile bool stopped;
        NamedPipeServerStream listener;
        readonly object pipeLock=new object();
        string pipe,token,uiToken,stamp="",scope="",workspace,staging,workspaceBinding="";
        bool automatic,reviewing,approvalPending,pendingProvider;
        int epoch,theme,approvalGeneration;
        long stateRevision;
        readonly string root=Path.GetDirectoryName(typeof(Connect).Assembly.Location);
        readonly string profile=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),"SlidePilot");
        readonly string data=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SlidePilot");
        public Connect() {StartupLog("COM class constructed; CLR "+Environment.Version+"; "+(IntPtr.Size*8)+"-bit");}
        void StartupLog(string message) {
            try {
                string folder=Path.Combine(data,"logs");Directory.CreateDirectory(folder);
                string file=Path.Combine(folder,"addin-startup.log");
                if(File.Exists(file) && new FileInfo(file).Length>1024*1024) File.WriteAllText(file,"");
                File.AppendAllText(file,DateTime.UtcNow.ToString("o")+" "+message+Environment.NewLine);
            } catch(IOException){}catch(UnauthorizedAccessException){}
        }
        static JavaScriptSerializer Json() {return new JavaScriptSerializer{MaxJsonLength=10*1024*1024,RecursionLimit=80};}
        public string GetCustomUI(string id) {
            StartupLog("GetCustomUI: "+id);
            return "<customUI xmlns='http://schemas.microsoft.com/office/2009/07/customui' onLoad='Loaded'><ribbon><tabs><tab id='SlidePilotTab' label='SlidePilot'><group id='SlidePilotTools' label='SlidePilot'><button id='SlidePilotChat' label='AI 助手' size='large' getImage='GetImage' onAction='OpenChat' screentip='打开 SlidePilot' supertip='在 AI 窗口中管理工作空间、阅读资料并生成可编辑幻灯片。'/><button id='SlidePilotSettings' label='设置' size='large' getImage='GetImage' onAction='OpenSettings' screentip='SlidePilot 设置' supertip='管理 AI 连接、安装状态及诊断。'/></group></tab></tabs></ribbon></customUI>";
        }
        IntPtr HostWindow(){try{return new IntPtr(Convert.ToInt64(app.HWND));}catch{return IntPtr.Zero;}}
        public object GetImage(Office.IRibbonControl control) {return RibbonIcons.Get(control.Id,HostWindow(),theme);}
        public void OpenSettings(Office.IRibbonControl control) {
            try {
                if(settingsProcess!=null && !settingsProcess.HasExited) {
                    if(settingsHandle==IntPtr.Zero){settingsProcess.Refresh();settingsHandle=settingsProcess.MainWindowHandle;}
                    if(settingsHandle!=IntPtr.Zero){PostMessage(settingsHandle,0x8047,IntPtr.Zero,IntPtr.Zero);SetForegroundWindow(settingsHandle);}return;
                }
                if(settingsProcess!=null)settingsProcess.Dispose();
                string entry=Path.Combine(root,@"Chatbox\settings-entry.cjs");
                if(!File.Exists(entry))throw new FileNotFoundException("产品设置文件缺失，请完整解压 SlidePilot 便携包后重试。",entry);
                settingsHandle=IntPtr.Zero;settingsProcess=Process.Start(ElectronStart(entry));WatchLaunch(settingsProcess,true);
            } catch(Exception e){MessageBox.Show(e.Message,"SlidePilot",MessageBoxButtons.OK,MessageBoxIcon.Error);}
        }
        public void Loaded(Office.IRibbonUI value) {ribbon=value;StartupLog("Ribbon loaded");HostHealth.RibbonLoaded(root);}
        public void OnConnection(object application,ext_ConnectMode mode,object addin,ref Array custom) {
            StartupLog("OnConnection: "+mode);
            try {ConnectHost(application);StartupLog("Host connected; ribbon available");}
            catch(Exception e) {
                StartupLog(e.ToString());
                Stop();
                MessageBox.Show("SlidePilot could not connect to PowerPoint.\r\n"+e.GetBaseException().Message+"\r\n\r\nDetails: "+Path.Combine(data,"logs","addin-startup.log"),"SlidePilot",MessageBoxButtons.OK,MessageBoxIcon.Error);
                throw;
            }
        }
        void ConnectHost(object application) {
            app=application;
            ui=new Control(); var handle=ui.Handle;
            Directory.CreateDirectory(profile);
            try {
                string preferences=Path.Combine(profile,"preferences.json");
                if(File.Exists(preferences)) {
                    var saved=Json().Deserialize<Dictionary<string,object>>(File.ReadAllText(preferences));object color;
                    if(saved.TryGetValue("theme",out color)){int value=Convert.ToInt32(color);if(value>=0 && value<=2)theme=value;}
                }
            } catch(Exception e){StartupLog("Preferences fallback: "+e.GetType().Name);}
            string stateFile=Path.Combine(profile,"workspace.txt");
            workspace=File.Exists(stateFile)?File.ReadAllText(stateFile):"";
            if(!Directory.Exists(workspace)) workspace=Path.Combine(profile,"Workspace");
            Directory.CreateDirectory(workspace);
            pipe="SlidePilot-"+Guid.NewGuid().ToString("N");
            byte[] bytes=new byte[32];
            using(var rng=RandomNumberGenerator.Create()) rng.GetBytes(bytes);
            token=BitConverter.ToString(bytes).Replace("-","");
            using(var rng=RandomNumberGenerator.Create()) rng.GetBytes(bytes);
            uiToken=BitConverter.ToString(bytes).Replace("-","");
            staging=Path.Combine(data,"sessions",pipe);
            Directory.CreateDirectory(staging);
            stopped=false;
            new Thread(Serve){IsBackground=true,Name="SlidePilot named pipe"}.Start();
            timer=new System.Windows.Forms.Timer{Interval=200};
            timer.Tick+=delegate {RefreshScope();};
            timer.Start();
            windowChanged=new WindowChanged(WindowActivated);
            try {ComEventsHelper.Combine(application,new Guid("914934C2-5A91-11CF-8700-00AA0060263B"),2010,windowChanged);} catch(COMException) {}
        }
        delegate void WindowChanged([MarshalAs(UnmanagedType.IDispatch)] object presentation,[MarshalAs(UnmanagedType.IDispatch)] object window);
        void WindowActivated(object presentation,object window) {RefreshScope();}
        public void OnStartupComplete(ref Array c) {}
        public void OnAddInsUpdate(ref Array c) {}
        public void OnBeginShutdown(ref Array c) {Stop();}
        public void OnDisconnection(ext_DisconnectMode mode,ref Array c) {Stop();}
        void Stop() {
            if(stopped) return; stopped=true;
            HostHealth.Clear();automatic=false;approvalGeneration++;
            if(timer!=null) timer.Dispose();
            if(launchTimer!=null) launchTimer.Dispose();
            if(settingsLaunchTimer!=null)settingsLaunchTimer.Dispose();
            try {if(windowChanged!=null) ComEventsHelper.Remove((object)app,new Guid("914934C2-5A91-11CF-8700-00AA0060263B"),2010,windowChanged);} catch(Exception) {}
            lock(pipeLock){if(listener!=null) listener.Dispose();}
            try {if(assistant!=null && !assistant.HasExited) assistant.CloseMainWindow();}catch(InvalidOperationException){}
            try {if(settingsProcess!=null && !settingsProcess.HasExited) settingsProcess.CloseMainWindow();}catch(InvalidOperationException){}
            if(ui!=null) ui.Dispose();
        }
        static long Identity(object value) {
            var p=Marshal.GetIUnknownForObject(value);
            try{return p.ToInt64();}finally{Marshal.Release(p);}
        }
        dynamic Deck() {if(app.Presentations.Count==0) throw new InvalidOperationException("Open a presentation in PowerPoint first.");return app.ActivePresentation;}
        void RefreshScope() {
            string next="";
            try {dynamic deck=Deck(); next=Identity((object)deck).ToString()+"|"+Convert.ToString(deck.FullName);}
            catch(Exception) {}
            if(next!=scope) {scope=next;ResetScope();}
        }
        void ResetScope() {automatic=false;approvalGeneration++;epoch++;stamp=pipe+"/"+epoch;}
        string Fingerprint() {
            RefreshScope();
            dynamic d=Deck(); var b=new StringBuilder(stamp);
            b.Append('|').Append((int)d.Slides.Count).Append('|').Append((int)d.Saved);
            try {
                dynamic win=app.ActiveWindow,sel=win.Selection;
                b.Append('|').Append((int)win.View.Slide.SlideID).Append('|').Append((int)sel.Type);
                if((int)sel.Type==2 || (int)sel.Type==3) {
                    foreach(dynamic sh in sel.ShapeRange) b.Append('/').Append((int)sh.Id);
                    if((int)sel.Type==3) b.Append(':').Append((int)sel.TextRange.Start).Append(':').Append((int)sel.TextRange.Length);
                }
            } catch(COMException) {}
            return b.ToString();
        }
        public bool GetAutomatic(Office.IRibbonControl c) {RefreshScope();return automatic;}
        public void SetAutomatic(Office.IRibbonControl c,bool pressed) {
            RefreshScope();
            if(!pressed){automatic=false;approvalGeneration++;return;}
            EnableAutomatic(delegate {
                using(var confirmation=new AutomaticApprovalDialog(Convert.ToString(Deck().Name),workspace)) {
                    IntPtr owner=HostWindow();
                    confirmation.Shown+=delegate{SetForegroundWindow(confirmation.Handle);};
                    return (owner==IntPtr.Zero?confirmation.ShowDialog():confirmation.ShowDialog(new OfficeWindow(owner)))==DialogResult.OK;
                }
            });
        }
        bool EnableAutomatic(Func<bool> confirm) {
            RefreshScope();
            if(scope=="" || automatic || approvalPending)return false;
            string expected=stamp;int generation=++approvalGeneration;approvalPending=true;
            try {
                if(confirm()) {
                    RefreshScope();
                    automatic=expected==stamp && generation==approvalGeneration && scope!="" && !stopped;
                }
                return automatic;
            } finally {approvalPending=false;}
        }
        public void SelectWorkspace(Office.IRibbonControl c) {
            using(var d=new WorkspaceChooser(workspace,Path.Combine(root,"examples","workspace"))) {
                IWin32Window owner=null;
                try {owner=new OfficeWindow(new IntPtr((int)app.HWND));} catch(Exception) {}
                if((owner==null?d.ShowDialog():d.ShowDialog(owner))!=DialogResult.OK)return;
                try {
                    File.WriteAllText(Path.Combine(profile,"workspace.txt"),d.SelectedPath);
                    workspace=d.SelectedPath;
                    ResetScope();
                } catch(Exception e){MessageBox.Show(d,"无法保存工作空间。\r\n"+e.Message,"SlidePilot",MessageBoxButtons.OK,MessageBoxIcon.Error);}
            }
        }
        sealed class OfficeWindow:IWin32Window {
            readonly IntPtr handle;
            public OfficeWindow(IntPtr value){handle=value;}
            public IntPtr Handle{get{return handle;}}
        }
        [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr handle);
        [DllImport("user32.dll")] static extern bool ShowWindowAsync(IntPtr handle,int cmd);
        [DllImport("user32.dll")] static extern bool PostMessage(IntPtr handle,uint message,IntPtr w,IntPtr l);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr handle,out uint processId);
        ProcessStartInfo ElectronStart(string entry) {
            var start=new ProcessStartInfo(Path.Combine(root,@"Electron\electron.exe"),"\""+entry+"\""){UseShellExecute=false,WorkingDirectory=root,CreateNoWindow=true};
            foreach(string flag in new[]{"ELECTRON_RUN_AS_NODE","NODE_OPTIONS","NODE_PATH","ELECTRON_RENDERER_URL","START_MINIMIZED","DEBUG_PROD"})start.EnvironmentVariables.Remove(flag);
            start.EnvironmentVariables["NODE_ENV"]="production";
            start.EnvironmentVariables["SLIDEPILOT_PIPE"]=pipe;start.EnvironmentVariables["SLIDEPILOT_TOKEN"]=token;
            start.EnvironmentVariables["SLIDEPILOT_UI_TOKEN"]=uiToken;start.EnvironmentVariables["SLIDEPILOT_STAGE"]=staging;
            start.EnvironmentVariables["SLIDEPILOT_HOST_PID"]=Process.GetCurrentProcess().Id.ToString();
            return start;
        }
        public void OpenChat(Office.IRibbonControl c) {
            try {
                if(assistant!=null && !assistant.HasExited) {assistant.Refresh();var h=assistant.MainWindowHandle;if(h!=IntPtr.Zero){ShowWindowAsync(h,9);SetForegroundWindow(h);}return;}
                if(assistant!=null) assistant.Dispose();
                foreach(string required in new[]{@"Electron\electron.exe",@"Chatbox\bootstrap.cjs",@"Chatbox\dist\renderer\index.html",@"Runtime\python.exe"})
                    if(!File.Exists(Path.Combine(root,required))) throw new FileNotFoundException("SlidePilot files are incomplete. Extract the complete portable ZIP, then run SlidePilot.Setup.exe again.",required);
                var start=new ProcessStartInfo(Path.Combine(root,@"Electron\electron.exe"),"\""+Path.Combine(root,"Chatbox")+"\"") {UseShellExecute=false,WorkingDirectory=root,CreateNoWindow=true};
                // Development shells and other Electron hosts can export these flags.
                // Inheriting RUN_AS_NODE makes a successful launch show no assistant UI.
                foreach(string flag in new[]{"ELECTRON_RUN_AS_NODE","NODE_OPTIONS","NODE_PATH","ELECTRON_RENDERER_URL","START_MINIMIZED","DEBUG_PROD"}) start.EnvironmentVariables.Remove(flag);
                start.EnvironmentVariables["NODE_ENV"]="production";
                start.EnvironmentVariables["SLIDEPILOT_PIPE"]=pipe;
                start.EnvironmentVariables["SLIDEPILOT_TOKEN"]=token;
                start.EnvironmentVariables["SLIDEPILOT_UI_TOKEN"]=uiToken;
                start.EnvironmentVariables["SLIDEPILOT_STAGE"]=staging;
                start.EnvironmentVariables["SLIDEPILOT_HOST_PID"]=Process.GetCurrentProcess().Id.ToString();
                assistant=Process.Start(start);
                WatchLaunch(assistant);
            } catch(Exception e){MessageBox.Show(e.Message,"SlidePilot");}
        }
        void WatchLaunch(Process process,bool settings=false) {
            var previous=settings?settingsLaunchTimer:launchTimer;if(previous!=null)previous.Dispose();
            DateTime deadline=DateTime.UtcNow.AddSeconds(60);
            var watch=new System.Windows.Forms.Timer{Interval=300};
            if(settings)settingsLaunchTimer=watch;else launchTimer=watch;
            watch.Tick+=delegate {
                try {
                    process.Refresh();
                    if(process.HasExited) {
                        int code=process.ExitCode;watch.Stop();
                        string message=(settings?"The settings window":"The AI assistant")+" closed before its window opened (exit 0x"+code.ToString("X8")+").\r\nRun SlidePilot.Setup.exe to check the portable files. Startup details: "+Path.Combine(data,"logs","assistant-startup.log");
                        try {Directory.CreateDirectory(Path.Combine(data,"logs"));File.AppendAllText(Path.Combine(data,"logs","assistant-startup.log"),DateTime.UtcNow.ToString("o")+" "+message+Environment.NewLine);}catch(IOException){}catch(UnauthorizedAccessException){}
                        if(!stopped) MessageBox.Show(message,"SlidePilot",MessageBoxButtons.OK,MessageBoxIcon.Error);
                    } else if(process.MainWindowHandle!=IntPtr.Zero || DateTime.UtcNow>=deadline) watch.Stop();
                } catch(InvalidOperationException){watch.Stop();}
            };
            watch.Start();
        }
        void Serve() {
            var user=WindowsIdentity.GetCurrent().User;
            var sec=new PipeSecurity();
            sec.SetAccessRuleProtection(true,false);
            sec.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.NetworkSid,null),PipeAccessRights.FullControl,AccessControlType.Deny));
            sec.AddAccessRule(new PipeAccessRule(user,PipeAccessRights.FullControl,AccessControlType.Allow));
            while(!stopped) try {
                using(var server=new NamedPipeServerStream(pipe,PipeDirection.InOut,1,PipeTransmissionMode.Byte,PipeOptions.None,65536,65536,sec)) {
                    lock(pipeLock){if(stopped)return;listener=server;}
                    server.WaitForConnection();
                    string response;
                    try {
                        var bytes=new MemoryStream();
                        int val;
                        while((val=server.ReadByte())!=-1 && val!=10) {if(bytes.Length>=8*1024*1024)throw new InvalidDataException("Request exceeds 8 MiB");bytes.WriteByte((byte)val);}
                        var req=Json().Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(bytes.ToArray()));
                        if(!String.Equals(Convert.ToString(req["token"]),token,StringComparison.Ordinal)) throw new UnauthorizedAccessException("Invalid session");
                        var result=ui.Invoke(new Func<object>(()=>Handle(req)));
                        response=Json().Serialize(new {result=result});
                    } catch(Exception e) {response=Json().Serialize(new {error=e.GetBaseException().Message});}
                    var buffer=Encoding.UTF8.GetBytes(response+"\n"); server.Write(buffer,0,buffer.Length);server.Flush();
                }
            } catch(Exception) {if(!stopped) Thread.Sleep(80);}
        }
        static Dictionary<string,object> Dict(object value) {return (Dictionary<string,object>)value;}
        object State(bool forAI=true) {
            bool provider=forAI && pendingProvider;if(forAI)pendingProvider=false;
            return new {automatic=automatic,hasDeck=scope!="",workspace=Path.GetFileName(workspace),workspaceId=workspaceBinding,document=scope==""?"":Convert.ToString(Deck().Name),revision=++stateRevision,theme=theme,provider=provider,approvalPending=approvalPending};
        }
        object SettingsState(){return new {theme=theme,version=typeof(Connect).Assembly.GetName().Version.ToString(3),office=Convert.ToString(app.Version)};}
        void SaveTheme(int value) {
            if(value<0 || value>2)throw new ArgumentException("Unknown icon palette.");
            string file=Path.Combine(profile,"preferences.json"),temporary=file+"."+Guid.NewGuid().ToString("N")+".tmp";
            var preferences=File.Exists(file)?Json().Deserialize<Dictionary<string,object>>(File.ReadAllText(file)):new Dictionary<string,object>();
            preferences["theme"]=value;
            try {
                File.WriteAllText(temporary,Json().Serialize(preferences),new UTF8Encoding(false));
                if(File.Exists(file))File.Replace(temporary,file,null);else File.Move(temporary,file);
            } finally {if(File.Exists(temporary))File.Delete(temporary);}
            theme=value;if(ribbon!=null)ribbon.Invalidate();
        }
        void OpenProductLocation(string target) {
            string destination;
            if(target=="logs" || target=="backups"){destination=Path.Combine(data,target);Directory.CreateDirectory(destination);}
            else if(target=="deployment")destination=Path.Combine(root,"SlidePilot.Setup.exe");
            else throw new ArgumentException("Unknown product location.");
            Process.Start(new ProcessStartInfo(destination){UseShellExecute=true,WorkingDirectory=root});
        }
        object Handle(Dictionary<string,object> req) {
            string action=Convert.ToString(req["action"]);RefreshScope();
            if(action.StartsWith("settings_",StringComparison.Ordinal)) {
                if(!req.ContainsKey("uiToken") || !String.Equals(uiToken,req["uiToken"] as string,StringComparison.Ordinal))throw new UnauthorizedAccessException("Settings window required");
                if(action=="settings_ready") {
                    var handle=new IntPtr(Convert.ToInt64(req["handle"]));uint pid;
                    GetWindowThreadProcessId(handle,out pid);
                    if(settingsProcess==null || settingsProcess.HasExited || pid!=(uint)settingsProcess.Id)throw new UnauthorizedAccessException("Unknown settings window");
                    settingsHandle=handle;return SettingsState();
                }
                if(action=="settings_read")return SettingsState();
                if(action=="settings_write"){SaveTheme(Convert.ToInt32(req["theme"]));return SettingsState();}
                if(action=="settings_provider"){pendingProvider=true;OpenChat(null);return new {opened=true};}
                if(action=="settings_open"){OpenProductLocation(Convert.ToString(req["target"]));return new {opened=true};}
                throw new ArgumentException("Unknown settings command");
            }
            if(action=="ui_approval" || action=="ui_workspace" || action=="ui_settings" || action=="ui_workspace_binding") {
                if(!req.ContainsKey("uiToken") || !String.Equals(uiToken,req["uiToken"] as string,StringComparison.Ordinal)) throw new UnauthorizedAccessException("Assistant control required");
                if(action=="ui_approval") SetAutomatic(null,!automatic);
                else if(action=="ui_workspace") SelectWorkspace(null);
                else if(action=="ui_settings")OpenSettings(null);
                else {
                    string binding=req.ContainsKey("workspaceId")?req["workspaceId"] as string:null;
                    if(binding==null || !System.Text.RegularExpressions.Regex.IsMatch(binding,@"\A[a-f0-9]{32}\z"))throw new ArgumentException("Invalid workspace binding.");
                    if(binding!=workspaceBinding){workspaceBinding=binding;ResetScope();}
                }
                action="ping";
            }
            if(action=="ping") return State(!req.ContainsKey("role") || Convert.ToString(req["role"])!="settings");
            if(action=="context") return new {binding=Fingerprint(),workspace=workspace,workspaceId=workspaceBinding,version=Convert.ToString(app.Version),document=Convert.ToString(Deck().Name),automatic=automatic};
            if(action=="inspect" || action=="chart_read") {
                if(!String.Equals(Convert.ToString(req["binding"]),Fingerprint()))
                    throw new InvalidOperationException("The presentation or selection changed. Read the context again.");
                if(action=="inspect") return Live.Inspect(Deck(),req);
                return Live.ChartRead(Deck(),req);
            }
            if(action!="mutate") throw new ArgumentException("Unknown host command");
            if(reviewing) throw new InvalidOperationException("Another change is in review.");
            string expected=Convert.ToString(req["binding"]),op=Convert.ToString(req["operation"]);
            if(!String.Equals(expected,Fingerprint())) throw new InvalidOperationException("The presentation or selection changed. Read the context again.");
            if(Array.IndexOf(new[]{"commit_draft","insert_draft","chart_add","chart_patch","chart_data","slide_edit"},op)<0) throw new ArgumentException("Unknown change");
            var args=Dict(req["args"]);
            reviewing=true;
            try {
                if(!automatic && !Approve(op,Json().Serialize(args))) throw new OperationCanceledException("User denied this operation. Wait for new instructions.");
                if(expected!=Fingerprint()) throw new InvalidOperationException("Presentation or selection changed during approval.");
                if(op=="commit_draft") return Commit(args);
                string backup=Backup(Deck());
                try {var result=Live.Change(Deck(),workspace,op,args);return new {result=result,backup=backup};}
                catch(Exception e){throw new InvalidOperationException("Change failed. Inspect the active document before retrying. Recovery copy: "+backup+". "+e.GetBaseException().Message);}
            } finally {reviewing=false;}
        }
        bool Approve(string op,string args) {
            using(var f=new Form{Text="SlidePilot · 审批",Width=680,Height=470,StartPosition=FormStartPosition.CenterScreen,MinimizeBox=false,MaximizeBox=false}) {
                var label=new Label{Dock=DockStyle.Top,Height=54,Text="演示文稿  "+Convert.ToString(Deck().Name)+"\r\n操作  "+op+"    工作空间  "+workspace,Padding=new Padding(8)};
                var box=new TextBox{Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Both,Dock=DockStyle.Fill,Text=args};
                var buttons=new FlowLayoutPanel{Dock=DockStyle.Bottom,Height=45,FlowDirection=FlowDirection.RightToLeft};
                var no=new Button{Text="拒绝",DialogResult=DialogResult.Cancel}; var yes=new Button{Text="批准一次",DialogResult=DialogResult.OK};
                buttons.Controls.Add(no);buttons.Controls.Add(yes);f.Controls.Add(box);f.Controls.Add(label);f.Controls.Add(buttons);f.CancelButton=no;f.AcceptButton=no;
                return f.ShowDialog()==DialogResult.OK;
            }
        }
        string Backup(dynamic deck) {
            string folder=Path.Combine(data,"backups");Directory.CreateDirectory(folder);
            // Preserve macros in the live recovery copy, including unsaved changes.
            string dest=Path.Combine(folder,DateTime.UtcNow.ToString("yyyyMMdd-HHmmssfff")+"-"+Guid.NewGuid().ToString("N")+".pptm");
            deck.SaveCopyAs(dest,25);return dest;
        }
        object Commit(Dictionary<string,object> args) {
            string id=(string)args["stage"],name=(string)args["filename"];
            Guid guid;
            if(!Guid.TryParseExact(id,"N",out guid)) throw new ArgumentException("Invalid staged file");
            string dest=Live.Draft(workspace,name,true);
            string src=Path.Combine(staging,id+".pptx");
            string hash;
            using(var file=File.OpenRead(src)) using(var sha=SHA256.Create()) hash=BitConverter.ToString(sha.ComputeHash(file)).Replace("-","").ToLowerInvariant();
            if(hash!=(string)args["sha256"]) throw new IOException("Staged draft changed");
            string temp=Path.Combine(Path.GetDirectoryName(dest),".slidepilot-"+id+".tmp");
            try {File.Copy(src,temp,false);File.Move(temp,dest);} finally {if(File.Exists(temp)) File.Delete(temp);}
            return new {file=@"_SlidePilot/drafts/"+name,sha256=hash};
        }
    }

    internal static class DialogStyle {
        internal static readonly Color Ink=Color.FromArgb(24,40,54),Muted=Color.FromArgb(95,113,128),Teal=Color.FromArgb(0,117,110),Surface=Color.FromArgb(245,248,250);
        internal static Label Label(string text,float size,bool bold=false) {
            return new Label{Text=text,AutoSize=true,Font=new Font("Microsoft YaHei UI",size,bold?FontStyle.Bold:FontStyle.Regular),ForeColor=bold?Ink:Muted,Margin=new Padding(0,0,0,10)};
        }
        internal static Button Button(string text,bool primary=false) {
            var button=new Button{Text=text,AutoSize=true,MinimumSize=new Size(106,38),Padding=new Padding(12,4,12,4),FlatStyle=FlatStyle.Flat,ForeColor=primary?Color.White:Ink,BackColor=primary?Teal:Color.White,Cursor=Cursors.Hand,Margin=new Padding(10,0,0,0)};
            button.FlatAppearance.BorderColor=primary?Teal:Color.FromArgb(215,224,230);return button;
        }
    }

    internal sealed class WorkspaceChooser:Form {
        readonly TextBox path;
        readonly Label status;
        public string SelectedPath{get;private set;}
        public WorkspaceChooser(string current,string example) {
            SuspendLayout();Text="SlidePilot · 工作空间";Font=new Font("Microsoft YaHei UI",9F);BackColor=DialogStyle.Surface;
            StartPosition=FormStartPosition.CenterParent;ShowInTaskbar=false;MinimizeBox=false;MaximizeBox=false;
            ClientSize=new Size(680,330);MinimumSize=new Size(600,365);
            var content=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=1,RowCount=7,Padding=new Padding(28),Margin=Padding.Empty};
            for(int i=0;i<7;i++)content.RowStyles.Add(new RowStyle(i==5?SizeType.Percent:SizeType.AutoSize,i==5?100:0));Controls.Add(content);
            content.Controls.Add(DialogStyle.Label("为这次创作选择资料",19,true),0,0);
            var description=DialogStyle.Label("在 AI 窗口中浏览工作空间。也可以直接粘贴资料文件夹路径。",9);description.MaximumSize=new Size(600,0);content.Controls.Add(description,0,1);
            var label=DialogStyle.Label("资料文件夹",9,true);label.Margin=new Padding(0,8,0,8);content.Controls.Add(label,0,2);
            var row=new TableLayoutPanel{Dock=DockStyle.Top,ColumnCount=2,AutoSize=true,Margin=Padding.Empty};row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));row.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,112));
            path=new TextBox{Text=current??"",Dock=DockStyle.Top,Margin=new Padding(0,7,0,0),AccessibleName="工作空间文件夹路径"};row.Controls.Add(path,0,0);
            var browse=DialogStyle.Button("浏览…");browse.Click+=delegate{
                using(var picker=new FolderBrowserDialog{Description="选择 SlidePilot 资料文件夹",SelectedPath=Directory.Exists(path.Text)?path.Text:current,ShowNewFolderButton=true})
                    if(picker.ShowDialog(this)==DialogResult.OK){path.Text=picker.SelectedPath;status.Text="文件夹已选择，点击“使用此文件夹”继续。";status.ForeColor=DialogStyle.Muted;}
            };row.Controls.Add(browse,1,0);content.Controls.Add(row,0,3);
            var formats=DialogStyle.Label("支持 PDF、Word、Excel、PPT、CSV 和文本资料。\r\n生成的演示文稿保存在此文件夹的 _SlidePilot / drafts 中。",9);formats.Margin=new Padding(0,14,0,8);formats.MaximumSize=new Size(600,0);content.Controls.Add(formats,0,4);
            status=DialogStyle.Label("",9);status.MaximumSize=new Size(600,0);content.Controls.Add(status,0,5);
            var footer=new TableLayoutPanel{Dock=DockStyle.Bottom,ColumnCount=2,AutoSize=true,Margin=Padding.Empty};footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));footer.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            var sample=new LinkLabel{Text="试用示例资料",AutoSize=true,LinkColor=DialogStyle.Teal,Margin=new Padding(0,10,0,0),Visible=Directory.Exists(example)};sample.LinkClicked+=delegate{path.Text=example;status.Text="已填入示例工作空间。";status.ForeColor=DialogStyle.Muted;};footer.Controls.Add(sample,0,0);
            var actions=new FlowLayoutPanel{AutoSize=true,FlowDirection=FlowDirection.LeftToRight,Margin=Padding.Empty};
            var cancel=DialogStyle.Button("取消");cancel.DialogResult=DialogResult.Cancel;
            var choose=DialogStyle.Button("使用此文件夹",true);choose.Click+=delegate{Choose();};actions.Controls.AddRange(new Control[]{cancel,choose});footer.Controls.Add(actions,1,0);content.Controls.Add(footer,0,6);
            AcceptButton=choose;CancelButton=cancel;Shown+=delegate{path.Focus();path.SelectAll();};
            AutoScaleDimensions=new SizeF(96,96);AutoScaleMode=AutoScaleMode.Dpi;ResumeLayout(true);
        }
        void Choose() {
            try {
                string value=Environment.ExpandEnvironmentVariables(path.Text.Trim().Trim('"'));
                if(!(value.StartsWith(@"\\") || (value.Length>=3 && Char.IsLetter(value[0]) && value[1]==':' && (value[2]=='\\' || value[2]=='/'))))
                    throw new ArgumentException("请输入完整文件夹路径，例如 D:\\资料\\季度简报。");
                value=Path.GetFullPath(value);
                if(!Directory.Exists(value))throw new DirectoryNotFoundException("找不到这个文件夹，请检查路径或点击“浏览”。");
                using(var entries=Directory.EnumerateFileSystemEntries(value).GetEnumerator())entries.MoveNext();
                SelectedPath=value;DialogResult=DialogResult.OK;Close();
            } catch(UnauthorizedAccessException){Error("无法读取此文件夹，请选择你有权访问的资料文件夹。");}
            catch(Exception e){Error(e.Message);}
        }
        void Error(string message){status.ForeColor=Color.FromArgb(176,53,53);status.Text=message;path.Focus();}
    }

    internal sealed class AutomaticApprovalDialog:Form {
        int stage;
        readonly Label title,step,body;
        readonly Button next,cancel;
        public AutomaticApprovalDialog(string document,string workspace) {
            SuspendLayout();Text="SlidePilot · 自动批准";Font=new Font("Microsoft YaHei UI",9F);BackColor=DialogStyle.Surface;
            StartPosition=FormStartPosition.CenterScreen;ClientSize=new Size(620,390);MinimumSize=new Size(620,425);ShowInTaskbar=false;MaximizeBox=false;MinimizeBox=false;
            var content=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=1,RowCount=6,Padding=new Padding(28)};
            for(int i=0;i<6;i++)content.RowStyles.Add(new RowStyle(i==4?SizeType.Percent:SizeType.AutoSize,i==4?100:0));Controls.Add(content);
            step=DialogStyle.Label("确认 1 / 2 · 了解范围",9,true);step.ForeColor=Color.FromArgb(176,53,53);content.Controls.Add(step,0,0);
            title=DialogStyle.Label("允许 AI 自动执行修改？",19,true);content.Controls.Add(title,0,1);
            body=DialogStyle.Label("启用后，AI 可修改当前演示文稿的文字、格式、图表与结构，无需逐项批准。修改当前文稿前会保存恢复副本。",10);body.MaximumSize=new Size(555,0);content.Controls.Add(body,0,2);
            var scope=new TextBox{Multiline=true,ReadOnly=true,BorderStyle=BorderStyle.None,BackColor=Color.FromArgb(235,241,244),ForeColor=DialogStyle.Ink,Dock=DockStyle.Top,Height=62,Text="演示文稿  "+document+"\r\n工作空间  "+workspace,Margin=new Padding(0,12,0,12)};content.Controls.Add(scope,0,3);
            var reminder=DialogStyle.Label("仅在本次 PowerPoint 会话中有效。切换演示文稿或工作空间后，将恢复逐次审批。",9);reminder.MaximumSize=new Size(555,0);content.Controls.Add(reminder,0,4);
            var actions=new FlowLayoutPanel{Dock=DockStyle.Bottom,AutoSize=true,FlowDirection=FlowDirection.RightToLeft,Margin=Padding.Empty};
            next=DialogStyle.Button("继续确认",true);next.BackColor=Color.FromArgb(176,53,53);next.FlatAppearance.BorderColor=next.BackColor;
            cancel=DialogStyle.Button("保持逐次审批");cancel.DialogResult=DialogResult.Cancel;
            next.Click+=delegate{
                if(stage==0){stage=1;step.Text="确认 2 / 2 · 最终确认";title.Text="确认启用自动批准";body.Text="AI 窗口将显示红色盾牌，表示自动批准已开启。你可以随时点击盾牌恢复逐次审批。\r\n\r\n是否现在启用？";next.Text="确认启用";cancel.Focus();}
                else {DialogResult=DialogResult.OK;Close();}
            };actions.Controls.AddRange(new Control[]{next,cancel});content.Controls.Add(actions,0,5);
            AcceptButton=cancel;CancelButton=cancel;Shown+=delegate{cancel.Focus();};
            AutoScaleDimensions=new SizeF(96,96);AutoScaleMode=AutoScaleMode.Dpi;ResumeLayout(true);
        }
    }

    internal static class RibbonIcons {
        static readonly Dictionary<string,object> Images=new Dictionary<string,object>();
        static readonly List<Bitmap> Bitmaps=new List<Bitmap>();
        [DllImport("user32.dll")] static extern uint GetDpiForWindow(IntPtr handle);
        internal static int SizeForDpi(int dpi){return Math.Max(32,Math.Min(96,(int)Math.Round(32*dpi/96.0)));}
        internal static object Get(string id,IntPtr window,int theme) {
            int dpi=96;try{uint value=GetDpiForWindow(window);if(value>0)dpi=(int)value;}catch(EntryPointNotFoundException){}
            int size=SizeForDpi(dpi);string key=id+":"+size+":"+theme;
            object picture;if(Images.TryGetValue(key,out picture))return picture;
            var bitmap=Draw(id,size,theme);picture=PictureHost.Convert(bitmap);Bitmaps.Add(bitmap);Images[key]=picture;return picture;
        }
        internal static Bitmap Draw(string id,int size,int theme) {
            var image=new Bitmap(size*4,size*4,System.Drawing.Imaging.PixelFormat.Format32bppArgb);image.SetResolution(96,96);
            Color ink=theme==1?Color.FromArgb(43,67,112):theme==2?Color.FromArgb(49,56,67):Color.FromArgb(38,83,74);
            Color accent=theme==1?Color.FromArgb(70,113,214):theme==2?Color.FromArgb(81,94,111):Color.FromArgb(35,153,125);
            Color faint=theme==1?Color.FromArgb(211,223,249):theme==2?Color.FromArgb(216,222,228):Color.FromArgb(201,234,224);
            using(var g=Graphics.FromImage(image))using(var pen=new Pen(ink,1.65F))using(var fill=new SolidBrush(faint)) {
                g.SmoothingMode=SmoothingMode.AntiAlias;g.PixelOffsetMode=PixelOffsetMode.HighQuality;g.Clear(Color.Transparent);g.ScaleTransform(size*4/32F,size*4/32F);pen.StartCap=pen.EndCap=LineCap.Round;pen.LineJoin=LineJoin.Round;
                if(id=="SlidePilotSettings") {
                    var gear=new List<PointF>();
                    for(int i=0;i<8;i++) {
                        double angle=i*Math.PI/4;
                        foreach(double offset in new[]{-0.34,-0.17,0.17,0.34}) {
                            float radius=Math.Abs(offset)<0.2?12.4F:9.8F;
                            gear.Add(new PointF(16+(float)Math.Cos(angle+offset)*radius,16+(float)Math.Sin(angle+offset)*radius));
                        }
                    }
                    g.FillPolygon(fill,gear.ToArray());g.DrawPolygon(pen,gear.ToArray());using(var ring=new Pen(accent,2F))g.DrawEllipse(ring,12,12,8,8);
                } else {
                    using(var outline=new GraphicsPath()) {
                        outline.AddArc(3,5,9,9,180,90);outline.AddArc(20,5,9,9,270,90);outline.AddArc(20,15,9,9,0,90);outline.AddLine(20,24,12,24);outline.AddLine(12,24,7,28);outline.AddLine(7,28,7,23);outline.AddArc(3,15,9,9,90,90);outline.CloseFigure();g.FillPath(fill,outline);g.DrawPath(pen,outline);
                    }
                    g.DrawLine(pen,10,12,20,12);g.DrawLine(pen,10,17,16,17);
                    using(var sparkle=new SolidBrush(accent))g.FillPolygon(sparkle,new[]{new PointF(25,1),new PointF(26.5F,4.5F),new PointF(30,6),new PointF(26.5F,7.5F),new PointF(25,11),new PointF(23.5F,7.5F),new PointF(20,6),new PointF(23.5F,4.5F)});
                }
            }
            var output=new Bitmap(size,size,System.Drawing.Imaging.PixelFormat.Format32bppArgb);
            using(var scaled=Graphics.FromImage(output)){scaled.InterpolationMode=InterpolationMode.HighQualityBicubic;scaled.PixelOffsetMode=PixelOffsetMode.HighQuality;scaled.DrawImage(image,new Rectangle(0,0,size,size));}
            image.Dispose();return output;
        }
        sealed class PictureHost:AxHost {
            private PictureHost():base(""){}
            internal static object Convert(Image image){return GetIPictureDispFromPicture(image);}
        }
    }
}
