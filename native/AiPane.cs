using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace SlidePilot {
    // Adapted from PagePilot AiPane: Chromium must remain an owned top-level
    // window. Reparenting it with WS_CHILD lets Office intercept text input.
    [ComVisible(true),Guid("CDA982C6-857A-47C2-89D4-CA6FDD533BC7"),ProgId("SlidePilot.AiPane")]
    public sealed class AiPane:UserControl {
        IntPtr child,owner,originalOwner;
        int originalStyle,originalExtendedStyle;
        WindowPlacement floatingPlacement;
        Rectangle lastBounds;
        readonly Timer tracking=new Timer{Interval=120};
        [StructLayout(LayoutKind.Sequential)] struct NativeRect {public int left,top,right,bottom;public Rectangle Rectangle {get{return Rectangle.FromLTRB(left,top,right,bottom);}}}
        [StructLayout(LayoutKind.Sequential)] struct WindowPlacement {public int length,flags,showCommand;public Point minimum,maximum;public NativeRect normal;}
        [StructLayout(LayoutKind.Sequential)] struct FrameMargins {public int left,right,top,bottom;}
        [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h,out NativeRect r);
        [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr h,out NativeRect r);
        [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr h,ref Point p);
        [DllImport("user32.dll")] static extern bool GetWindowPlacement(IntPtr h,ref WindowPlacement value);
        [DllImport("user32.dll")] static extern bool SetWindowPlacement(IntPtr h,ref WindowPlacement value);
        [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h,int index);
        [DllImport("user32.dll",EntryPoint="GetWindowLongPtrW")] static extern IntPtr GetWindowLongPtr(IntPtr h,int index);
        [DllImport("user32.dll")] static extern int SetWindowLong(IntPtr h,int index,int value);
        [DllImport("user32.dll",EntryPoint="SetWindowLongPtrW")] static extern IntPtr SetWindowLongPtr(IntPtr h,int index,IntPtr value);
        [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h,IntPtr after,int x,int y,int width,int height,uint flags);
        [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h,int command);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
        [DllImport("user32.dll")] static extern bool IsWindowEnabled(IntPtr h);
        [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
        [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
        [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr h,uint flags);
        [DllImport("user32.dll")] static extern int SetWindowRgn(IntPtr h,IntPtr region,bool redraw);
        [DllImport("gdi32.dll")] static extern IntPtr CreateRectRgn(int left,int top,int right,int bottom);
        [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr h);
        [DllImport("dwmapi.dll")] static extern int DwmExtendFrameIntoClientArea(IntPtr h,ref FrameMargins margins);
        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h,int attribute,ref int value,int size);
        static IntPtr WindowOwner(IntPtr h){return IntPtr.Size==8?GetWindowLongPtr(h,-8):new IntPtr(GetWindowLong(h,-8));}
        static void WindowOwner(IntPtr h,IntPtr value){if(IntPtr.Size==8)SetWindowLongPtr(h,-8,value);else SetWindowLong(h,-8,value.ToInt32());}
        static void Frame(IntPtr h,bool docked) {
            try {int policy=docked?1:0;DwmSetWindowAttribute(h,2,ref policy,4);if(docked){var margins=new FrameMargins();DwmExtendFrameIntoClientArea(h,ref margins);}}
            catch(DllNotFoundException){}catch(EntryPointNotFoundException){}
        }
        public AiPane(){AutoScaleMode=AutoScaleMode.Dpi;BackColor=Color.White;tracking.Tick+=delegate{Fit();};}
        internal bool Attached {get{return child!=IntPtr.Zero;}}
        internal void Attach(IntPtr window) {
            if(window==IntPtr.Zero || !IsWindow(window))throw new InvalidOperationException("The assistant window is no longer available.");
            if(child==window){Fit();return;}
            if(child!=IntPtr.Zero)Detach();
            if(!IsHandleCreated)CreateControl();
            child=window;originalOwner=WindowOwner(child);originalStyle=GetWindowLong(child,-16);originalExtendedStyle=GetWindowLong(child,-20);
            floatingPlacement=new WindowPlacement{length=Marshal.SizeOf(typeof(WindowPlacement))};
            if(!GetWindowPlacement(child,ref floatingPlacement)){child=IntPtr.Zero;throw new InvalidOperationException("Could not read the assistant window position.");}
            if(floatingPlacement.showCommand==2 || floatingPlacement.showCommand==3)ShowWindow(child,9);
            owner=GetAncestor(Handle,2);
            WindowOwner(child,owner);
            SetWindowLong(child,-16,(originalStyle & ~0x00C40000 & ~0x40000000)|unchecked((int)0x80000000));
            SetWindowLong(child,-20,originalExtendedStyle & ~0x00000301);Frame(child,true);
            SetWindowPos(child,IntPtr.Zero,0,0,0,0,0x37);
            lastBounds=Rectangle.Empty;Fit();tracking.Start();
        }
        internal void Detach() {
            tracking.Stop();var window=child;child=IntPtr.Zero;
            if(window==IntPtr.Zero || !IsWindow(window))return;
            SetWindowRgn(window,IntPtr.Zero,true);WindowOwner(window,originalOwner!=IntPtr.Zero && IsWindow(originalOwner)?originalOwner:IntPtr.Zero);
            SetWindowLong(window,-16,originalStyle);SetWindowLong(window,-20,originalExtendedStyle);Frame(window,false);
            SetWindowPos(window,IntPtr.Zero,0,0,0,0,0x37);
            // Restore pre-dock placement, including a maximized floating window.
            if(floatingPlacement.showCommand==2)floatingPlacement.showCommand=1;
            SetWindowPlacement(window,ref floatingPlacement);ShowWindow(window,floatingPlacement.showCommand==3?3:4);
            owner=IntPtr.Zero;lastBounds=Rectangle.Empty;
        }
        internal static Rectangle WindowBounds(Rectangle pane,Rectangle outer,Rectangle client,Point clientOrigin) {
            return new Rectangle(pane.X-(clientOrigin.X-outer.X),pane.Y-(clientOrigin.Y-outer.Y),
                pane.Width+Math.Max(0,outer.Width-client.Width),pane.Height+Math.Max(0,outer.Height-client.Height));
        }
        void Fit() {
            if(child==IntPtr.Zero || !IsHandleCreated)return;
            if(!IsWindow(child)){tracking.Stop();child=IntPtr.Zero;return;}
            if(!Visible || !IsWindowVisible(Handle) || IsIconic(owner) || !IsWindowEnabled(owner)){ShowWindow(child,0);return;}
            Rectangle bounds=RectangleToScreen(ClientRectangle);
            if(bounds.Width<20 || bounds.Height<20){ShowWindow(child,0);return;}
            if(bounds!=lastBounds) {
                NativeRect outer,client;if(!GetWindowRect(child,out outer) || !GetClientRect(child,out client))return;
                var origin=new Point();if(!ClientToScreen(child,ref origin))return;
                Rectangle placement=WindowBounds(bounds,outer.Rectangle,client.Rectangle,origin);
                SetWindowPos(child,IntPtr.Zero,placement.X,placement.Y,placement.Width,placement.Height,0x34);
                int left=bounds.X-placement.X,top=bounds.Y-placement.Y;
                IntPtr region=CreateRectRgn(left,top,left+bounds.Width,top+bounds.Height);
                if(SetWindowRgn(child,region,true)==0)DeleteObject(region);
                lastBounds=bounds;
            }
            ShowWindow(child,4);
        }
        protected override void OnResize(EventArgs e){base.OnResize(e);Fit();}
        protected override void OnVisibleChanged(EventArgs e){base.OnVisibleChanged(e);Fit();}
        protected override void Dispose(bool disposing){if(disposing){Detach();tracking.Dispose();}base.Dispose(disposing);}
    }
    internal static class AiModeTransition {
        internal static void Validate(string mode){if(mode!="window" && mode!="sidebar")throw new ArgumentException("Choose sidebar or window mode.");}
        internal static string Change(string previous,string next,Action<string> apply,Action<string> persist) {
            Validate(next);
            try {apply(next);persist(next);return next;}
            catch {try{apply(previous);}catch{}throw;}
        }
    }
    internal sealed class TaskPaneSizing {
        string lastMeasurement;
        internal bool Applied {get;private set;}
        internal int RequestedWidth {get;private set;}
        internal static int InitialWidth(int hostPixels,int dpi,int currentUnits,int currentPixels) {
            if(hostPixels<=0 || dpi<=0 || currentUnits<=0 || currentPixels<=0)throw new ArgumentOutOfRangeException("Task pane sizing requires real, nonzero window measurements.");
            double pixels=480.0*dpi/96;
            pixels=Math.Min(pixels,Math.Floor(hostPixels*0.44));
            // Office documents Width in points. Read back the visible pane's
            // unit/pixel ratio to accommodate Office DPI virtualization rather
            // than assuming that COM Width is a physical pixel measurement.
            double unitsPerPixel=(double)currentUnits/currentPixels;
            return Math.Max(1,(int)Math.Floor(pixels*unitsPerPixel));
        }
        internal bool Observe(int hostPixels,int dpi,int currentUnits,int currentPixels,Action<int> resize) {
            if(Applied)return false;
            if(hostPixels<=0 || dpi<=0 || currentUnits<=0 || currentPixels<=0){lastMeasurement=null;return false;}
            string measurement=hostPixels+":"+dpi+":"+currentUnits+":"+currentPixels;
            if(lastMeasurement!=measurement){lastMeasurement=measurement;return false;}
            int width=InitialWidth(hostPixels,dpi,currentUnits,currentPixels);
            resize(width);RequestedWidth=width;Applied=true;return true;
        }
    }
}
