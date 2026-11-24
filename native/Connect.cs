using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
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
    }
    [ComVisible(true),Guid("FB9007D1-2CB9-4C9D-8FC4-4A96CA980A3E"),ProgId("SlidePilot.PowerPoint"),ClassInterface(ClassInterfaceType.None),ComDefaultInterface(typeof(IRibbon))]
    public sealed class Connect:IDTExtensibility2,Office.IRibbonExtensibility,IRibbon {
        dynamic app;
        Control ui;
        Office.IRibbonUI ribbon;
        Process assistant;
        System.Windows.Forms.Timer timer;
        volatile bool stopped;
        NamedPipeServerStream listener;
        readonly object pipeLock=new object();
        string pipe,token,uiToken,stamp="",scope="",workspace,staging;
        bool automatic,reviewing;
        int epoch;
        readonly string root=Path.GetDirectoryName(typeof(Connect).Assembly.Location);
        readonly string profile=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),"SlidePilot");
        readonly string data=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SlidePilot");
        static JavaScriptSerializer Json() {return new JavaScriptSerializer{MaxJsonLength=10*1024*1024,RecursionLimit=80};}
        public string GetCustomUI(string id) {
            return "<customUI xmlns='http://schemas.microsoft.com/office/2009/07/customui' onLoad='Loaded'><ribbon><tabs><tab id='SlidePilotTab' label='SlidePilot'><group id='SlidePilotTools' label='SlidePilot'><button id='SlidePilotChat' label='AI 助手' size='large' imageMso='NewComment' onAction='OpenChat'/><button id='SlidePilotWorkspace' label='选择工作空间' imageMso='FileOpen' onAction='SelectWorkspace'/><toggleButton id='SlidePilotApproval' label='自动批准此演示文稿' getPressed='GetAutomatic' onAction='SetAutomatic' imageMso='AcceptInvitation'/></group></tab></tabs></ribbon></customUI>";
        }
        public void Loaded(Office.IRibbonUI value) {ribbon=value;}
        public void OnConnection(object application,ext_ConnectMode mode,object addin,ref Array custom) {
            app=application;
            ui=new Control(); var handle=ui.Handle;
            Directory.CreateDirectory(profile);
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
            try {ComEventsHelper.Combine(application,new Guid("914934C2-5A91-11CF-8700-00AA0060263B"),2010,new WindowChanged(WindowActivated));} catch(COMException) {}
        }
        delegate void WindowChanged([MarshalAs(UnmanagedType.IDispatch)] object presentation,[MarshalAs(UnmanagedType.IDispatch)] object window);
        void WindowActivated(object presentation,object window) {RefreshScope();}
        public void OnStartupComplete(ref Array c) {}
        public void OnAddInsUpdate(ref Array c) {}
        public void OnBeginShutdown(ref Array c) {Stop();}
        public void OnDisconnection(ext_DisconnectMode mode,ref Array c) {Stop();}
        void Stop() {
            if(stopped) return; stopped=true;
            if(timer!=null) timer.Dispose();
            lock(pipeLock){if(listener!=null) listener.Dispose();}
            try {if(assistant!=null && !assistant.HasExited) assistant.CloseMainWindow();}catch(InvalidOperationException){}
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
        void ResetScope() {automatic=false;epoch++;stamp=pipe+"/"+epoch;if(ribbon!=null) ribbon.InvalidateControl("SlidePilotApproval");}
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
            if(pressed && scope!="" && MessageBox.Show("允许本次会话中对此演示文稿和当前工作空间的后续写入？切换文稿或工作空间后会恢复逐次审批。","SlidePilot",MessageBoxButtons.YesNo,MessageBoxIcon.Question,MessageBoxDefaultButton.Button2)==DialogResult.Yes) automatic=true;
            else automatic=false;
            if(ribbon!=null) ribbon.InvalidateControl("SlidePilotApproval");
        }
        public void SelectWorkspace(Office.IRibbonControl c) {
            using(var d=new FolderBrowserDialog{Description="选择 SlidePilot 资料工作空间",SelectedPath=workspace}) if(d.ShowDialog()==DialogResult.OK) {
                workspace=Path.GetFullPath(d.SelectedPath);
                File.WriteAllText(Path.Combine(profile,"workspace.txt"),workspace);
                ResetScope();
            }
        }
        [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr handle);
        [DllImport("user32.dll")] static extern bool ShowWindowAsync(IntPtr handle,int cmd);
        public void OpenChat(Office.IRibbonControl c) {
            try {
                if(assistant!=null && !assistant.HasExited) {assistant.Refresh();var h=assistant.MainWindowHandle;if(h!=IntPtr.Zero){ShowWindowAsync(h,9);SetForegroundWindow(h);}return;}
                var start=new ProcessStartInfo(Path.Combine(root,@"Electron\electron.exe"),"\""+Path.Combine(root,"Chatbox")+"\"") {UseShellExecute=false,WorkingDirectory=root};
                start.EnvironmentVariables["SLIDEPILOT_PIPE"]=pipe;
                start.EnvironmentVariables["SLIDEPILOT_TOKEN"]=token;
                start.EnvironmentVariables["SLIDEPILOT_UI_TOKEN"]=uiToken;
                start.EnvironmentVariables["SLIDEPILOT_STAGE"]=staging;
                start.EnvironmentVariables["SLIDEPILOT_HOST_PID"]=Process.GetCurrentProcess().Id.ToString();
                assistant=Process.Start(start);
            } catch(Exception e){MessageBox.Show(e.Message,"SlidePilot");}
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
        object Handle(Dictionary<string,object> req) {
            string action=Convert.ToString(req["action"]);RefreshScope();
            if(action=="ui_approval" || action=="ui_workspace") {
                if(!req.ContainsKey("uiToken") || !String.Equals(uiToken,req["uiToken"] as string,StringComparison.Ordinal)) throw new UnauthorizedAccessException("Assistant control required");
                if(action=="ui_approval") SetAutomatic(null,!automatic); else SelectWorkspace(null);
                action="ping";
            }
            if(action=="ping") return new {automatic=automatic,hasDeck=scope!="",workspace=Path.GetFileName(workspace)};
            if(action=="context") return new {binding=Fingerprint(),workspace=workspace,version=Convert.ToString(app.Version),document=Convert.ToString(Deck().Name),automatic=automatic};
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
}
