using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

// Real HWND checks on a newly created desktop that is NEVER switched to the
// input desktop. Only this process's three fixture windows are manipulated.
// Exit 77 means the environment refused desktop isolation; it is not a pass.
class AiPaneWin32Regression {
    [StructLayout(LayoutKind.Sequential)] struct Rect {public int left,top,right,bottom;public Rectangle Value{get{return Rectangle.FromLTRB(left,top,right,bottom);}}}
    [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr CreateDesktop(string name,string device,IntPtr mode,uint flags,uint access,IntPtr security);
    [DllImport("user32.dll",SetLastError=true)] static extern bool SetThreadDesktop(IntPtr desktop);
    [DllImport("user32.dll",SetLastError=true)] static extern bool CloseDesktop(IntPtr desktop);
    [DllImport("user32.dll")] static extern IntPtr GetThreadDesktop(uint thread);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool GetUserObjectInformation(IntPtr value,int index,StringBuilder output,uint size,out uint needed);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window,out uint process);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window,out Rect rectangle);
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr window,out Rect rectangle);
    [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr window,ref Point origin);
    [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr window,int index);
    [DllImport("user32.dll",EntryPoint="GetWindowLongPtrW")] static extern IntPtr GetWindowLongPtr(IntPtr window,int index);
    [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr window,uint flags);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] static extern bool IsZoomed(IntPtr window);
    [DllImport("user32.dll")] static extern int GetWindowRgn(IntPtr window,IntPtr region);
    [DllImport("gdi32.dll")] static extern IntPtr CreateRectRgn(int left,int top,int right,int bottom);
    [DllImport("gdi32.dll")] static extern int GetRgnBox(IntPtr region,out Rect rectangle);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr region);
    static int checks,result=1;
    static IntPtr desktop;
    static string desktopName;
    static void Assert(bool value,string message){if(!value)throw new Exception(message);checks++;}
    static string DesktopName(IntPtr handle){var name=new StringBuilder(256);uint needed;if(!GetUserObjectInformation(handle,2,name,512,out needed))throw new Win32Exception(Marshal.GetLastWin32Error());return name.ToString();}
    static void AssertOwnWindow(IntPtr handle){uint pid;uint thread=GetWindowThreadProcessId(handle,out pid);Assert(pid==(uint)Process.GetCurrentProcess().Id && DesktopName(GetThreadDesktop(thread))==desktopName,"Window must belong to this process on the isolated desktop.");}
    static IntPtr Owner(IntPtr handle){return IntPtr.Size==8?GetWindowLongPtr(handle,-8):new IntPtr(GetWindowLong(handle,-8));}
    static Rectangle Bounds(IntPtr handle){Rect bounds;if(!GetWindowRect(handle,out bounds))throw new Win32Exception();return bounds.Value;}
    static Rectangle ClientBounds(IntPtr handle){Rect bounds;var origin=new Point();if(!GetClientRect(handle,out bounds)||!ClientToScreen(handle,ref origin))throw new Win32Exception();return new Rectangle(origin,bounds.Value.Size);}
    static void Pump(int milliseconds){var watch=Stopwatch.StartNew();while(watch.ElapsedMilliseconds<milliseconds){Application.DoEvents();Thread.Sleep(10);}}
    static void Aligned(Control pane,IntPtr floating,string label) {
        Rectangle expected=pane.RectangleToScreen(pane.ClientRectangle),actual=ClientBounds(floating);
        Assert(expected==actual,label+": client content must align with the pane. Expected "+expected+"; actual "+actual);
        IntPtr region=CreateRectRgn(0,0,0,0);
        try {Rect clipped;Assert(GetWindowRgn(floating,region)!=0 && GetRgnBox(region,out clipped)!=0,"Docked window must have a clipping region.");
            GetRgnBox(region,out clipped);var screen=Bounds(floating);var projected=new Rectangle(screen.X+clipped.left,screen.Y+clipped.top,clipped.right-clipped.left,clipped.bottom-clipped.top);
            Assert(projected==expected,label+": clipping must match the pane.");
        }finally{DeleteObject(region);}
        Console.WriteLine(label+": client="+actual);
    }
    static void Check(string assemblyPath) {
        var assembly=Assembly.LoadFrom(assemblyPath);var paneType=assembly.GetType("SlidePilot.AiPane",true);
        var attach=paneType.GetMethod("Attach",BindingFlags.Instance|BindingFlags.NonPublic);var detach=paneType.GetMethod("Detach",BindingFlags.Instance|BindingFlags.NonPublic);
        using(var host=new Form{Text="SlidePilot isolated host fixture",StartPosition=FormStartPosition.Manual,Location=new Point(20,30),ClientSize=new Size(1160,780),ShowInTaskbar=false})
        using(var originalOwner=new Form{Text="SlidePilot isolated owner fixture",StartPosition=FormStartPosition.Manual,Bounds=new Rectangle(40,50,200,140),ShowInTaskbar=false})
        using(var floating=new Form{Text="SlidePilot isolated assistant fixture",StartPosition=FormStartPosition.Manual,Bounds=new Rectangle(90,100,760,560),ShowInTaskbar=false})
        using(var pane=(Control)Activator.CreateInstance(paneType)) {
            pane.Dock=DockStyle.Right;pane.Width=480;host.Controls.Add(pane);
            host.Show();originalOwner.Show();floating.Show(originalOwner);Pump(250);
            IntPtr hwnd=floating.Handle;AssertOwnWindow(hwnd);AssertOwnWindow(host.Handle);AssertOwnWindow(originalOwner.Handle);
            int style=GetWindowLong(hwnd,-16),extended=GetWindowLong(hwnd,-20);Rectangle original=Bounds(hwnd);IntPtr priorOwner=Owner(hwnd);
            Assert(priorOwner==originalOwner.Handle,"The test must begin with its own nonzero owner.");
            Console.WriteLine("Before: hwnd=0x"+hwnd.ToInt64().ToString("X")+" bounds="+original+" style=0x"+style.ToString("X8"));
            try {
                for(int round=0;round<3;round++) {
                    attach.Invoke(pane,new object[]{hwnd});Pump(300);
                    Assert(floating.Handle==hwnd,"Docking must preserve the HWND.");
                    Assert(Owner(hwnd)==host.Handle,"Docking must assign the fixture host as owner.");
                    Assert(GetAncestor(hwnd,2)==hwnd && (GetWindowLong(hwnd,-16)&0x40000000)==0,"Docked Chromium surrogate must remain top-level, not WS_CHILD.");
                    Assert((GetWindowLong(hwnd,-16)&0x00C40000)==0 && (GetWindowLong(hwnd,-16)&unchecked((int)0x80000000))!=0,"Docking must remove caption/resize frame and add popup style.");
                    Aligned(pane,hwnd,"Dock "+(round+1));
                    pane.Width=280;Pump(260);Aligned(pane,hwnd,"Narrow "+(round+1));
                    pane.Width=640;Pump(260);Aligned(pane,hwnd,"Wide "+(round+1));
                    host.Location=new Point(60+round*10,70+round*10);Pump(260);Aligned(pane,hwnd,"Move "+(round+1));
                    detach.Invoke(pane,null);Pump(250);
                    Assert(floating.Handle==hwnd,"Detaching must preserve the HWND.");
                    Assert(Owner(hwnd)==priorOwner,"Detaching must restore the original owner.");
                    Assert(GetWindowLong(hwnd,-16)==style && GetWindowLong(hwnd,-20)==extended,"Detaching must restore styles exactly.");
                    Assert(Bounds(hwnd)==original,"Detaching must restore the floating location and size. Expected "+original+"; actual "+Bounds(hwnd));
                    IntPtr region=CreateRectRgn(0,0,0,0);try{Assert(GetWindowRgn(hwnd,region)==0,"Detaching must clear the sidebar clipping region.");}finally{DeleteObject(region);}
                    Console.WriteLine("Restore "+(round+1)+": hwnd=0x"+hwnd.ToInt64().ToString("X")+" bounds="+Bounds(hwnd));
                }
                floating.WindowState=FormWindowState.Maximized;Pump(250);Assert(IsZoomed(hwnd),"Fixture must be maximized before the maximized round trip.");
                attach.Invoke(pane,new object[]{hwnd});Pump(250);Assert(!IsZoomed(hwnd),"Docking must normalize a maximized floating window.");
                detach.Invoke(pane,null);Pump(250);Assert(IsZoomed(hwnd) && floating.Handle==hwnd,"Detaching must restore maximization without replacing the HWND.");
            } finally {detach.Invoke(pane,null);floating.Close();originalOwner.Close();host.Close();Pump(50);}
        }
    }
    static void Worker(string assemblyPath) {
        try {
            desktopName="SlidePilot-Geometry-Test-"+Guid.NewGuid().ToString("N");
            // READOBJECTS | CREATEWINDOW | CREATEMENU | WRITEOBJECTS. Deliberately
            // omit DESKTOP_SWITCHDESKTOP: this harness cannot activate it.
            desktop=CreateDesktop(desktopName,null,IntPtr.Zero,0,0x87,IntPtr.Zero);
            if(desktop==IntPtr.Zero){Console.WriteLine("SKIP: CreateDesktop denied/unavailable; Win32 error "+Marshal.GetLastWin32Error()+". No windows created.");result=77;return;}
            if(!SetThreadDesktop(desktop)){Console.WriteLine("SKIP: SetThreadDesktop unavailable; Win32 error "+Marshal.GetLastWin32Error()+". No windows created.");result=77;return;}
            Assert(DesktopName(GetThreadDesktop(GetCurrentThreadId()))==desktopName,"Worker must be on the newly created isolated desktop before creating forms.");
            Check(assemblyPath);Console.WriteLine(checks+" real Win32 checks passed on an isolated desktop. This does not test Office CTP or Electron.");result=0;
        } catch(Exception e){Console.Error.WriteLine("FAIL: "+e.GetBaseException());result=1;}
    }
    static int Main(string[] args) {
        if(args.Length!=1){Console.Error.WriteLine("Pass the built SlidePilot.PowerPoint.dll path.");return 2;}
        string assemblyPath=Path.GetFullPath(args[0]);if(!File.Exists(assemblyPath)){Console.Error.WriteLine("Add-in assembly not found.");return 2;}
        var worker=new Thread(()=>Worker(assemblyPath)){IsBackground=true,Name="SlidePilot isolated geometry test"};worker.SetApartmentState(ApartmentState.STA);worker.Start();
        if(!worker.Join(30000)){Console.Error.WriteLine("FAIL: isolated geometry test timed out; terminating only this test process.");return 1;}
        if(desktop!=IntPtr.Zero && !CloseDesktop(desktop))Console.WriteLine("Desktop handle cleanup deferred to test-process exit; Win32 error "+Marshal.GetLastWin32Error()+".");
        return result;
    }
}
