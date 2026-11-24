using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

public sealed class FixturePresentations { public int Count {get;set;} }
public sealed class FixtureSlides { public int Count {get{return 1;}} }
public sealed class FixtureDeck { public string Name {get;set;} public string FullName {get;set;} public FixtureSlides Slides {get{return new FixtureSlides();}} public int Saved {get{return -1;}} }
public sealed class FixtureApplication {
    public FixturePresentations Presentations {get;set;}
    public FixtureDeck ActivePresentation {get;set;}
    public string Version {get{return "16.0";}}
    public object ActiveWindow {get{throw new COMException("No selection in this fixture.");}}
}
class HostStateRegression {
    static int checks;
    static void Assert(bool value,string message){if(!value)throw new Exception(message);checks++;}
    static BindingFlags Private=BindingFlags.Instance|BindingFlags.NonPublic;
    [STAThread] static int Main(string[] args) {
        if(args.Length!=1){Console.Error.WriteLine("Pass the built SlidePilot.PowerPoint.dll path.");return 2;}
        var assembly=Assembly.LoadFrom(Path.GetFullPath(args[0]));var type=assembly.GetType("SlidePilot.Connect",true);
        var host=Activator.CreateInstance(type);var app=new FixtureApplication{Presentations=new FixturePresentations{Count=0},ActivePresentation=new FixtureDeck{Name="First",FullName="First.pptx"}};
        type.GetField("app",Private).SetValue(host,app);type.GetField("workspace",Private).SetValue(host,Path.GetTempPath());
        var enable=type.GetMethod("EnableAutomatic",Private);var automatic=type.GetField("automatic",Private);
        Func<Func<bool>,bool> request=confirm=>(bool)enable.Invoke(host,new object[]{confirm});
        Action disable=()=>type.GetMethod("SetAutomatic").Invoke(host,new object[]{null,false});
        int prompts=0;Assert(!request(()=>{prompts++;return true;}) && prompts==0,"No-document requests must not show confirmation.");
        app.Presentations.Count=1;
        Assert(!request(()=>false) && !(bool)automatic.GetValue(host),"Cancel must keep manual approval.");
        Assert(request(()=>true) && (bool)automatic.GetValue(host),"Confirmed current scope should enable automatic approval.");
        disable();Assert(!(bool)automatic.GetValue(host),"Disabling must require no confirmation.");
        Assert(!request(()=>{app.ActivePresentation=new FixtureDeck{Name="Second",FullName="Second.pptx"};return true;}),"A document switch must invalidate an outstanding confirmation.");
        int nested=0;Assert(request(()=>{Assert(!request(()=>{nested++;return true;}),"Nested approval must be refused.");return true;}) && nested==0,"Only the outer confirmation may run.");
        disable();Assert(!request(()=>{disable();return true;}),"Disabling while confirmation is open must invalidate it.");
        bool failed=false;try{request(()=>{throw new IOException("Fixture cancellation");});}catch(TargetInvocationException){failed=true;}
        Assert(failed && !(bool)type.GetField("approvalPending",Private).GetValue(host),"A failed dialog must release the pending guard.");
        Assert(request(()=>true),"Approval must recover after a failed dialog.");
        var state=type.GetMethod("State",Private);var first=state.Invoke(host,new object[]{false});var second=state.Invoke(host,new object[]{false});
        Assert((long)second.GetType().GetProperty("revision").GetValue(second,null)>(long)first.GetType().GetProperty("revision").GetValue(first,null),"State revisions must strictly increase.");
        app.ActivePresentation=new FixtureDeck{Name="Third",FullName="Third.pptx"};
        Assert(!(bool)type.GetMethod("GetAutomatic").Invoke(host,new object[]{null}),"Returning to another document must restore manual approval.");
        type.GetField("uiToken",Private).SetValue(host,"fixture-ui-token");
        var handle=type.GetMethod("Handle",Private);var stamp=type.GetField("stamp",Private);
        Func<string,string,object> bind=(id,key)=>handle.Invoke(host,new object[]{new Dictionary<string,object>{{"action","ui_workspace_binding"},{"workspaceId",id},{"uiToken",key}}});
        string firstId=new string('a',32),secondId=new string('b',32);
        request(()=>true);string oldStamp=(string)stamp.GetValue(host);var firstBinding=bind(firstId,"fixture-ui-token");
        Assert(!(bool)automatic.GetValue(host) && oldStamp!=(string)stamp.GetValue(host),"First workspace binding must invalidate prior consent.");
        Assert((string)firstBinding.GetType().GetProperty("workspaceId").GetValue(firstBinding,null)==firstId,"Workspace binding response must report the current workspace.");
        request(()=>true);oldStamp=(string)stamp.GetValue(host);bind(firstId,"fixture-ui-token");
        Assert((bool)automatic.GetValue(host) && oldStamp==(string)stamp.GetValue(host),"Repeated binding to the same workspace must preserve consent and stamp.");
        bind(secondId,"fixture-ui-token");Assert(!(bool)automatic.GetValue(host) && oldStamp!=(string)stamp.GetValue(host),"A different workspace must invalidate consent and outstanding context.");
        foreach(string invalid in new[]{new string('A',32),new string('a',31),new string('z',32),firstId+"\n"}) {
            bool rejected=false;try{bind(invalid,"fixture-ui-token");}catch(TargetInvocationException e){rejected=e.InnerException is ArgumentException;}
            Assert(rejected,"Malformed workspace identifiers must be rejected.");
        }
        bool unauthorized=false;try{bind(firstId,"incorrect");}catch(TargetInvocationException e){unauthorized=e.InnerException is UnauthorizedAccessException;}
        Assert(unauthorized && (string)type.GetField("workspaceBinding",Private).GetValue(host)==secondId,"Untrusted callers must not change the workspace binding.");
        Assert(!request(()=>{bind(firstId,"fixture-ui-token");return true;}),"Workspace changes during confirmation must invalidate that confirmation.");
        var context=handle.Invoke(host,new object[]{new Dictionary<string,object>{{"action","context"}}});
        Assert((string)context.GetType().GetProperty("workspaceId").GetValue(context,null)==firstId,"Tool context must expose the current UI workspace binding.");
        var icons=assembly.GetType("SlidePilot.RibbonIcons",true);var size=icons.GetMethod("SizeForDpi",BindingFlags.Static|BindingFlags.NonPublic);var draw=icons.GetMethod("Draw",BindingFlags.Static|BindingFlags.NonPublic);
        Assert((int)size.Invoke(null,new object[]{96})==32 && (int)size.Invoke(null,new object[]{144})==48 && (int)size.Invoke(null,new object[]{288})==96,"Icon sizes must track supported display scales.");
        int? previous=null;
        for(int theme=0;theme<3;theme++)using(var bitmap=(Bitmap)draw.Invoke(null,new object[]{"SlidePilotSettings",48,theme})) {
            Assert(bitmap.Width==48 && bitmap.Height==48 && bitmap.GetPixel(0,0).A==0,"Rendered icon must retain size and transparent corners.");
            int pixel=bitmap.GetPixel(24,24).ToArgb();if(previous.HasValue)Assert(pixel!=previous.Value,"Each theme must produce a distinct palette.");previous=pixel;
        }
        Console.WriteLine(checks+" host approval, state revision and icon checks passed.");return 0;
    }
}
