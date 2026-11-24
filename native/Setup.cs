using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace SlidePilot {
    public static class SetupProgram {
        [STAThread]
        public static int Main(string[] args) {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException+=delegate(object sender,System.Threading.ThreadExceptionEventArgs e) {
                MessageBox.Show(e.Exception.Message,"SlidePilot",MessageBoxButtons.OK,MessageBoxIcon.Error);
            };
            Application.Run(new SetupWindow(Array.IndexOf(args,"--machine")>=0,Array.IndexOf(args,"--replace-existing")>=0));
            return 0;
        }
    }

    public sealed class SetupWindow:Form {
        readonly string root=AppDomain.CurrentDomain.BaseDirectory;
        readonly string logDir=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SlidePilot","logs");
        readonly Color ink=Color.FromArgb(24,40,54),muted=Color.FromArgb(95,113,128),teal=Color.FromArgb(0,117,110);
        Label heading,subtitle,badge,summary,hint,locationTitle,checksTitle,footer,sideText;
        Label[] checkNames=new Label[4],checkValues=new Label[4];
        Button enable,disable,refresh,launch,copy,logs,rollback;
        CheckBox replaceOld;
        RadioButton userScope,machineScope;
        Label scopeTitle;
        TextBox details;
        ComboBox language;
        ProgressBar progress;
        bool chinese=true,busy,ready,registered,foreign,owned;
        bool Machine {get{return machineScope!=null && machineScope.Checked;}}
        string powerpoint,excel;
        string T(string zh,string en) {return chinese?zh:en;}
        Label Label(string text,float size,Color color,bool bold=false) {
            return new Label{Text=text,AutoSize=true,ForeColor=color,Font=new Font("Microsoft YaHei UI",size,bold?FontStyle.Bold:FontStyle.Regular),Margin=new Padding(0,0,0,7)};
        }
        Button Button(string text,EventHandler click,bool primary=false) {
            var button=new Button{Text=text,AutoSize=false,Size=new Size(primary?164:132,42),Padding=new Padding(7,4,7,4),FlatStyle=FlatStyle.Flat,BackColor=primary?teal:Color.White,ForeColor=primary?Color.White:ink,Cursor=Cursors.Hand,Margin=new Padding(0,0,10,0)};
            button.FlatAppearance.BorderColor=primary?teal:Color.FromArgb(215,224,230);
            button.Click+=click; return button;
        }
        public SetupWindow(bool machine,bool replace=false) {
            SuspendLayout();
            Text="SlidePilot · 安装与管理"; Font=new Font("Microsoft YaHei UI",9F);
            StartPosition=FormStartPosition.CenterScreen; ClientSize=new Size(980,770);
            MinimumSize=new Size(720,520); BackColor=Color.FromArgb(245,248,250);
            try {Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);}catch(Exception){}
            var shell=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=2,RowCount=1};
            shell.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,202)); shell.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100)); Controls.Add(shell);
            var side=new Panel{Dock=DockStyle.Fill,BackColor=ink,Padding=new Padding(25,32,20,24),Margin=Padding.Empty}; shell.Controls.Add(side,0,0);
            var sideFlow=new FlowLayoutPanel{Dock=DockStyle.Fill,FlowDirection=FlowDirection.TopDown,WrapContents=false}; side.Controls.Add(sideFlow);
            var mark=new PictureBox{Size=new Size(58,52),Margin=new Padding(0,0,0,22)};
            mark.Paint+=delegate(object sender,PaintEventArgs e){
                e.Graphics.SmoothingMode=System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                using(var accent=new SolidBrush(Color.FromArgb(107,231,202)))
                using(var pen=new Pen(accent,2.6F)){
                    e.Graphics.DrawRectangle(pen,4,5,44,30);
                    e.Graphics.DrawLines(pen,new[]{new Point(15,27),new Point(22,21),new Point(27,24),new Point(38,13)});
                    e.Graphics.DrawLine(pen,26,36,26,43);e.Graphics.DrawLine(pen,16,44,36,44);
                }
            };sideFlow.Controls.Add(mark);
            sideFlow.Controls.Add(Label("SlidePilot",19,Color.White,true));
            sideFlow.Controls.Add(Label("FOR POWERPOINT",8,Color.FromArgb(157,184,195)));
            sideText=Label("",10,Color.FromArgb(202,219,226));sideText.MaximumSize=new Size(155,0);sideText.Margin=new Padding(0,32,0,0);sideFlow.Controls.Add(sideText);
            var version=Label("0.1.0 RC4\nWindows · Portable",8,Color.FromArgb(157,184,195));version.Dock=DockStyle.Bottom;side.Controls.Add(version);

            var content=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=1,RowCount=8,Padding=new Padding(28,25,28,18),Margin=Padding.Empty};
            for(int i=0;i<8;i++) content.RowStyles.Add(new RowStyle(i==5?SizeType.Percent:SizeType.AutoSize,i==5?100:0));
            var scroll=new Panel{Dock=DockStyle.Fill,AutoScroll=true,Margin=Padding.Empty};
            content.Dock=DockStyle.Top;content.AutoSize=true;scroll.Controls.Add(content);shell.Controls.Add(scroll,1,0);
            var top=new TableLayoutPanel{Dock=DockStyle.Top,AutoSize=true,ColumnCount=2,Margin=Padding.Empty};top.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));top.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,116));
            heading=Label("",21,ink,true); top.Controls.Add(heading,0,0);
            language=new ComboBox{DropDownStyle=ComboBoxStyle.DropDownList,Dock=DockStyle.Top,Margin=new Padding(0,4,0,0)};
            language.Items.AddRange(new object[]{"简体中文","English"});language.SelectedIndex=0;language.AccessibleName="Language / 语言";
            language.SelectedIndexChanged+=delegate{chinese=language.SelectedIndex==0; Localize();RefreshChecks(false);};top.Controls.Add(language,1,0);content.Controls.Add(top,0,0);
            subtitle=Label("",9,muted);subtitle.Margin=new Padding(0,0,0,18);content.Controls.Add(subtitle,0,1);

            var status=new TableLayoutPanel{Dock=DockStyle.Top,AutoSize=true,ColumnCount=1,BackColor=Color.FromArgb(232,245,240),Padding=new Padding(18,13,18,12),Margin=new Padding(0,0,0,18)};
            badge=Label("",9,teal,true);summary=Label("",13,ink,true);hint=Label("",9,muted);hint.MaximumSize=new Size(610,0);
            status.Controls.Add(badge);status.Controls.Add(summary);status.Controls.Add(hint);content.Controls.Add(status,0,2);

            var checks=new TableLayoutPanel{Dock=DockStyle.Top,AutoSize=true,ColumnCount=2,Padding=new Padding(0),Margin=new Padding(0,0,0,14)};
            checks.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,154));checks.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
            checksTitle=Label("",10,ink,true);checks.Controls.Add(checksTitle,0,0);checks.SetColumnSpan(checksTitle,2);
            for(int i=0;i<4;i++) {checkNames[i]=Label("",9,muted);checkValues[i]=Label("",9,ink);checkValues[i].MaximumSize=new Size(440,0);checks.Controls.Add(checkNames[i],0,i+1);checks.Controls.Add(checkValues[i],1,i+1);}
            locationTitle=Label("",9,muted);checks.Controls.Add(locationTitle,0,5);
            var path=new TextBox{ReadOnly=true,Text=root.TrimEnd(Path.DirectorySeparatorChar),BorderStyle=BorderStyle.None,BackColor=BackColor,Dock=DockStyle.Top,Margin=new Padding(0,3,0,5),AccessibleName="Installation folder"};checks.Controls.Add(path,1,5);content.Controls.Add(checks,0,3);
            scopeTitle=Label("",9,muted);checks.Controls.Add(scopeTitle,0,6);
            var scopes=new FlowLayoutPanel{AutoSize=true,Dock=DockStyle.Top,Margin=Padding.Empty};
            userScope=new RadioButton{AutoSize=true,Checked=!machine,Margin=new Padding(0,0,18,0)};
            machineScope=new RadioButton{AutoSize=true,Checked=machine,Margin=Padding.Empty};
            scopes.Controls.AddRange(new Control[]{userScope,machineScope});checks.Controls.Add(scopes,1,6);
            replaceOld=new CheckBox{AutoSize=true,MaximumSize=new Size(470,0),Visible=machine,Checked=machine&&replace,Margin=new Padding(0,4,0,4)};
            checks.Controls.Add(replaceOld,1,7);
            machineScope.CheckedChanged+=delegate{if(!busy){Localize();RefreshChecks(true);}};

            var actionRow=new FlowLayoutPanel{Dock=DockStyle.Top,AutoSize=true,WrapContents=true,Margin=new Padding(0,0,0,12)};
            enable=Button("",async delegate{await Deploy("enable");},true); disable=Button("",async delegate{await Deploy("disable");}); refresh=Button("",delegate{RefreshChecks(true);});
            rollback=Button("",async delegate{await Deploy("rollback");});
            actionRow.Controls.AddRange(new Control[]{enable,disable,rollback,refresh});content.Controls.Add(actionRow,0,4);
            details=new TextBox{Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill,BackColor=Color.White,ForeColor=muted,BorderStyle=BorderStyle.FixedSingle,MinimumSize=new Size(0,105),Margin=new Padding(0,0,0,10),AccessibleName="Diagnostics / 诊断详情"};content.Controls.Add(details,0,5);
            progress=new ProgressBar{Dock=DockStyle.Top,Height=4,Style=ProgressBarStyle.Continuous,Margin=new Padding(0,0,0,10)};content.Controls.Add(progress,0,6);
            var bottom=new TableLayoutPanel{Dock=DockStyle.Top,AutoSize=true,ColumnCount=1,Margin=Padding.Empty};
            var links=new FlowLayoutPanel{Dock=DockStyle.Top,AutoSize=true,WrapContents=true,Margin=new Padding(0,0,0,9)};
            launch=Button("",async delegate{await VerifyPowerPoint();});copy=Button("",delegate{try{Clipboard.SetText(details.Text);footer.Text=T("诊断信息已复制。","Diagnostics copied.");}catch(Exception e){Append(e.Message);}});logs=Button("",delegate{try{Directory.CreateDirectory(logDir);SafeOpen(logDir);}catch(Exception e){Append(e.Message);}});
            launch.Width=180;copy.Width=132;logs.Width=112;
            links.Controls.AddRange(new Control[]{launch,copy,logs});bottom.Controls.Add(links,0,0);footer=Label("",8,muted);footer.MaximumSize=new Size(650,0);bottom.Controls.Add(footer,0,1);content.Controls.Add(bottom,0,7);
            FormClosing+=delegate(object sender,FormClosingEventArgs e){if(busy)e.Cancel=true;};
            Localize();AutoScaleDimensions=new SizeF(96,96);AutoScaleMode=AutoScaleMode.Dpi;ResumeLayout(true);
            Shown+=delegate{var area=Screen.FromControl(this).WorkingArea;Size=new Size(Math.Min(Width,area.Width),Math.Min(Height,area.Height));CenterToScreen();RefreshChecks(true);};
        }
        void Localize() {
            Text=T("SlidePilot · 安装与管理","SlidePilot · Setup & manage");heading.Text=T("安装与验证","Setup and verification");
            subtitle.Text=T("启用 PowerPoint 插件，开始用资料制作可编辑演示文稿。","Enable your PowerPoint assistant for editable, source-based presentations.");
            sideText.Text=T("部署管理器","Deployment manager");checksTitle.Text=T("环境与安装状态","Environment & installation");
            checkNames[0].Text="PowerPoint";checkNames[1].Text=T("运行文件","Portable files");checkNames[2].Text=T("插件注册","Registration");checkNames[3].Text="Excel";locationTitle.Text=T("当前位置","Current folder");
            disable.Text=T("停用插件","Disable");refresh.Text=T("重新检查","Refresh");launch.Text=T("打开 PowerPoint","Open PowerPoint");copy.Text=T("复制诊断","Copy diagnostics");logs.Text=T("查看日志","Open logs");
            launch.Text=T("启动并验证 PowerPoint","Verify in PowerPoint");
            replaceOld.Visible=Machine;if(!Machine)replaceOld.Checked=false;
            replaceOld.Text=T("备份并替换当前账户和整台电脑的旧注册","Back up and replace old user and machine registrations");
            rollback.Text=T("回滚版本","Roll back");scopeTitle.Text=T("安装范围","Install for");userScope.Text=T("仅当前用户","Current user");machineScope.Text=T("整台电脑（管理员）","All users (administrator)");
            footer.Text=Machine?T("整机部署请使用管理员管理、其他账户可读取的固定目录。","Use a fixed location controlled by administrators and readable by all users."):T("仅为当前用户启用 · 保留此文件夹 · 不需要管理员权限或 PowerShell","Current user only · Keep this folder in place · No administrator or PowerShell required");
        }
        void Append(string value) {
            details.AppendText(value+Environment.NewLine);details.SelectionStart=details.TextLength;details.ScrollToCaret();
        }
        void RefreshChecks(bool writeLog) {
            if(busy)return;
            try {
                var missing=Manager.MissingFiles(root);powerpoint=Manager.OfficePath("POWERPNT.EXE");excel=Manager.OfficePath("EXCEL.EXE");
                registered=true;owned=false;foreign=false;bool failedLoad=false;var registration=new StringBuilder();
                foreach(var view in Manager.Views) {
                    int behavior;
                    string path=Manager.Registration(view,out behavior,Machine);
                    bool same=Manager.SameCodebase(path,Manager.Codebase(root));
                    bool complete=Manager.RegistrationComplete(view,root,Machine);
                    registered &= complete;
                    owned |= same;
                    failedLoad |= same && behavior==2;
                    foreign |= path!=null && !same;
                    registration.AppendLine(view+": "+(path??"(disabled)")+"; LoadBehavior="+behavior);
                    if(same && behavior==3 && !complete)
                        registration.AppendLine(T("侧栏或插件注册不完整。点击启用以修复当前安装。","Incomplete add-in or sidebar registration. Enable to repair this installation."));
                }
                ready=missing.Length==0 && powerpoint!=null;
                checkValues[0].Text=powerpoint==null?T("未检测到桌面版 PowerPoint","Desktop PowerPoint not found"):T("已检测到桌面版","Desktop version detected");
                checkValues[1].Text=missing.Length==0?T("完整 · 内置运行时已就绪","Complete · bundled runtimes ready"):T("缺少 ","Missing ")+missing.Length+T(" 项文件"," files");
                checkValues[2].Text=registered?T("已启用 · 当前文件夹","Enabled · current folder"):failedLoad?T("上次加载失败 · 请修复","Previous load failed · repair needed"):foreign?T("另一个文件夹已注册","Another folder is registered"):T("尚未启用 / 需要修复","Not enabled / needs repair");
                checkValues[3].Text=excel==null?T("未检测到 · 图表数据编辑需要 Excel","Not found · required to edit chart data"):T("已就绪 · 可编辑内嵌图表数据","Ready · edit embedded chart data");
                enable.Text=owned?T("修复 / 重新启用","Repair / re-enable"):foreign?T("切换到此版本","Use this version"):T("启用 SlidePilot","Enable SlidePilot");
                enable.Enabled=ready;disable.Enabled=owned && !foreign;rollback.Enabled=Manager.HasRollback(Machine);launch.Enabled=powerpoint!=null && !Manager.IsAdministrator();
                badge.Text=registered?T("已启用","ENABLED"):ready?T("准备就绪","READY TO ENABLE"):T("需要处理","ACTION NEEDED");
                summary.Text=registered?T("打开 PowerPoint，开始使用","Open PowerPoint to get started"):ready?T("一键启用，随时可停用","One click to enable. Easy to disable."):T("请先完成环境检查","Complete the environment checks");
                hint.Text=registered?T("在 SlidePilot 选项卡打开 AI 助手，在对话窗口管理工作空间和审批。","Open the AI assistant on the SlidePilot tab. Manage workspace and approvals in the chat window."):foreign?T("启用后将切换到当前文件夹。您的工作区、聊天记录和其他插件会保留。","Enabling switches registration to this folder. Your workspace, chats and other add-ins are preserved."):ready?T("使用前请保存并关闭 PowerPoint。启用后保留当前文件夹。","Save and close PowerPoint before enabling. Keep this folder in place afterwards."):T("请完整解压便携包，并安装桌面版 PowerPoint。下方列出了具体问题。","Extract the full portable package and install desktop PowerPoint. See the details below.");
                if(failedLoad){badge.Text=T("需要修复","REPAIR NEEDED");summary.Text=T("PowerPoint 上次未能加载插件","PowerPoint could not load the add-in");hint.Text=T("请先关闭 PowerPoint，再修复并重新打开。若仍失败，可查看日志中的启动原因。","Close PowerPoint, repair, then reopen it. If loading still fails, check the startup log.");}
                if(HostHealth.IsLoaded(root)){badge.Text=T("功能区已加载","RIBBON LOADED");summary.Text=T("PowerPoint 已加载此版本的功能区","PowerPoint has loaded this version’s ribbon");}
                if(writeLog) {
                    details.Clear();Append("SlidePilot 0.1.0 RC4 · "+DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));Append("Scope: "+(Machine?"All users (HKLM)":"Current user (HKCU)")+"; Administrator: "+Manager.IsAdministrator());Append("Folder: "+root);Append("PowerPoint: "+(powerpoint??"not found"));Append("Excel: "+(excel??"not found"));Append(registration.ToString().TrimEnd());
                    if(missing.Length>0)Append("Missing: "+String.Join(", ",missing));
                    if(Machine && Manager.HasUserOverride())Append(T("检测到当前账户的旧注册。若要迁移到整台电脑，请勾选“备份并替换”，再启用此版本。","A per-user registration exists. To migrate it, select Back up and replace, then enable this version."));
                    if(Manager.IsAdministrator())Append(T("当前安装器以管理员运行。请从开始菜单正常打开 PowerPoint；提升运行的 Office 可能不加载仅当前用户插件。","Setup is elevated. Open PowerPoint normally from Start; elevated Office may ignore per-user COM registration."));
                    Append(T("更改前请保存并关闭 PowerPoint；无需关闭 PagePilot 或 MailPilot。","Save and close PowerPoint before changes. PagePilot and MailPilot can stay open."));
                }
            }catch(Exception e){ready=false;enable.Enabled=false;disable.Enabled=false;badge.Text=T("检查失败","CHECK FAILED");summary.Text=T("无法读取安装状态","Unable to read installation status");hint.Text=e.Message;Append(e.ToString());}
        }
        async Task Deploy(string verb) {
            if(busy)return;
            if(Machine && !Manager.IsAdministrator()) {
                try {Process.Start(new ProcessStartInfo(Application.ExecutablePath,replaceOld.Checked?"--machine --replace-existing":"--machine"){UseShellExecute=true,Verb="runas"});footer.Text=T("请在管理员安装窗口继续操作。","Continue in the administrator setup window.");}
                catch(System.ComponentModel.Win32Exception e){Append(e.NativeErrorCode==1223?T("已取消管理员授权；未更改安装状态。","Administrator request cancelled; nothing changed."):e.Message);}
                return;
            }
            var processes=Process.GetProcessesByName("POWERPNT");bool running=processes.Length>0;foreach(var p in processes)p.Dispose();
            if(running){MessageBox.Show(this,T("请先保存并关闭 PowerPoint，再点击此按钮。","Save and close PowerPoint, then try again."),"SlidePilot",MessageBoxButtons.OK,MessageBoxIcon.Information);return;}
            busy=true;enable.Enabled=disable.Enabled=rollback.Enabled=refresh.Enabled=launch.Enabled=language.Enabled=userScope.Enabled=machineScope.Enabled=false;progress.Style=ProgressBarStyle.Marquee;
            badge.Text=T("正在处理","WORKING");summary.Text=verb=="enable"?T("正在启用 SlidePilot…","Enabling SlidePilot…"):verb=="rollback"?T("正在恢复上一次注册…","Restoring registration…"):T("正在停用插件…","Disabling the add-in…");
            try {
                bool machine=Machine,replace=Machine&&replaceOld.Checked&&verb=="enable";var writer=new StringWriter();int result=await Task.Run(()=>Manager.Run(verb,root,writer,machine,replace));
                string report=DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")+" · "+verb+Environment.NewLine+writer.ToString();Append(report);
                try{Directory.CreateDirectory(logDir);File.AppendAllText(Path.Combine(logDir,"setup.log"),report+Environment.NewLine,Encoding.UTF8);}catch(Exception e){Append("Log: "+e.Message);}
                busy=false;RefreshChecks(false);
                if(result!=0){badge.Text=T("操作未完成","COULD NOT COMPLETE");summary.Text=T("请查看下方诊断详情","See diagnostics below");hint.Text=T("请查看操作结果和恢复状态。","See the operation result and recovery status below.");}
                else {progress.Style=ProgressBarStyle.Continuous;progress.Value=100;if(verb=="disable"){summary.Text=T("插件已停用，资料和设置已保留","Disabled. Your files and settings are preserved.");hint.Text=T("重新启用时，点击上方启用按钮即可。","You can enable it again whenever you need it.");}}
            }catch(Exception e){Append(e.ToString());badge.Text=T("操作失败","FAILED");summary.Text=e.Message;}
            finally{busy=false;refresh.Enabled=language.Enabled=userScope.Enabled=machineScope.Enabled=true;enable.Enabled=ready;disable.Enabled=owned && !foreign;rollback.Enabled=Manager.HasRollback(Machine);launch.Enabled=powerpoint!=null && !Manager.IsAdministrator();progress.Style=ProgressBarStyle.Continuous;}
        }
        async Task VerifyPowerPoint() {
            if(busy||powerpoint==null||Manager.IsAdministrator())return;
            if(HostHealth.IsLoaded(root)){RefreshChecks(true);return;}
            busy=true;
            enable.Enabled=disable.Enabled=rollback.Enabled=refresh.Enabled=launch.Enabled=false;
            language.Enabled=userScope.Enabled=machineScope.Enabled=false;
            footer.Text=T("等待 PowerPoint 加载此版本的功能区…","Waiting for PowerPoint to load this ribbon…");
            progress.Style=ProgressBarStyle.Marquee;
            bool loaded=false;
            try {
                using(var started=Process.Start(new ProcessStartInfo(powerpoint){UseShellExecute=true})){}
                for(int attempt=0;attempt<60&&!loaded;attempt++){
                    await Task.Delay(500);
                    loaded=HostHealth.IsLoaded(root);
                }
                footer.Text=loaded?T("已收到此版本的功能区加载回执。","PowerPoint confirmed this ribbon loaded."):
                    T("30 秒内未收到功能区回执。请打开一份演示文稿，查看“禁用项目”并重新检查。","No ribbon confirmation within 30 seconds. Open a presentation, check Disabled Items, then refresh.");
                Append(footer.Text);
            }catch(Exception e){Append(e.Message);footer.Text=e.Message;}
            finally{busy=false;language.Enabled=userScope.Enabled=machineScope.Enabled=refresh.Enabled=true;progress.Style=ProgressBarStyle.Continuous;RefreshChecks(false);}
        }
        void SafeOpen(string path) {try{if(!String.IsNullOrWhiteSpace(path))Process.Start(new ProcessStartInfo(path){UseShellExecute=true});}catch(Exception e){Append(e.Message);MessageBox.Show(this,e.Message,"SlidePilot",MessageBoxButtons.OK,MessageBoxIcon.Error);}}
    }
}
