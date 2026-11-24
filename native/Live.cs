using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;

namespace SlidePilot {
    internal static class Live {
        static int Num(Dictionary<string,object> d,string k,int fallback) {return d.ContainsKey(k)?Convert.ToInt32(d[k],CultureInfo.InvariantCulture):fallback;}
        static float Pos(Dictionary<string,object> d,string k,float fallback) {return d.ContainsKey(k)?Convert.ToSingle(d[k],CultureInfo.InvariantCulture):fallback;}
        static string Str(Dictionary<string,object> d,string k,string fallback="") {return d.ContainsKey(k)?Convert.ToString(d[k],CultureInfo.InvariantCulture):fallback;}
        static List<object> Items(object value) {var list=new List<object>();foreach(var item in (IEnumerable)value) list.Add(item);return list;}
        public static string Draft(string workspace,string name,bool create) {
            if(String.IsNullOrWhiteSpace(name) || name!=Path.GetFileName(name) || !name.EndsWith(".pptx",StringComparison.OrdinalIgnoreCase)
               || name.IndexOfAny(Path.GetInvalidFileNameChars())>=0 || Regex.IsMatch(name,@"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)",RegexOptions.IgnoreCase))
                throw new ArgumentException("Use one .pptx filename.");
            string path=workspace;
            foreach(string p in new[]{"_SlidePilot","drafts"}) {
                path=Path.Combine(path,p);
                if(Directory.Exists(path) && (File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0) throw new IOException("Draft folder is a reparse point");
                if(create) Directory.CreateDirectory(path);
            }
            path=Path.Combine(path,name);
            if(File.Exists(path) && (File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0) throw new IOException("Draft file is a reparse point");
            return path;
        }
        static dynamic Slide(dynamic deck,Dictionary<string,object> args) {return deck.Slides.FindBySlideID(Num(args,"slideId",0));}
        static dynamic Shape(dynamic slide,int id) {
            foreach(dynamic sh in slide.Shapes) if((int)sh.Id==id) return sh;
            throw new ArgumentException("Shape ID no longer exists. Inspect again.");
        }
        static dynamic Chart(dynamic deck,Dictionary<string,object> args) {
            dynamic sh=Shape(Slide(deck,args),Num(args,"shapeId",0));
            if((int)sh.HasChart==0) throw new ArgumentException("Shape does not contain a native chart");
            return sh.Chart;
        }
        public static object Inspect(dynamic d,Dictionary<string,object> args) {
            int start=Math.Max(1,Num(args,"start",1)),limit=Math.Min(100,Math.Max(1,Num(args,"limit",20)));
            int id=Num(args,"slideId",0),count=(int)d.Slides.Count;
            var slideList=new List<object>();
            if(id>0){dynamic selected=d.Slides.FindBySlideID(id);start=(int)selected.SlideIndex;limit=1;}
            for(int i=start;i<=count && i<start+limit;i++) {
                dynamic s=d.Slides[i];var shapes=new List<object>();
                foreach(dynamic sh in s.Shapes) {
                    string text="";
                    try{if((int)sh.HasTextFrame!=0 && (int)sh.TextFrame.HasText!=0) text=Convert.ToString(sh.TextFrame.TextRange.Text);}catch(System.Runtime.InteropServices.COMException){}
                    shapes.Add(new {shapeId=(int)sh.Id,name=(string)sh.Name,type=(int)sh.Type,chart=(int)sh.HasChart!=0,table=(int)sh.HasTable!=0,
                        left=(float)sh.Left,top=(float)sh.Top,width=(float)sh.Width,height=(float)sh.Height,text=text.Length>500?text.Substring(0,500):text});
                }
                slideList.Add(new {slideId=(int)s.SlideID,index=i,shapes=shapes});
            }
            return new {name=(string)d.Name,count=count,width=(float)d.PageSetup.SlideWidth,height=(float)d.PageSetup.SlideHeight,slides=slideList};
        }
        public static object ChartRead(dynamic d,Dictionary<string,object> args) {
            object chart=Chart(d,args);
            var results=new List<object>();
            foreach(var p in Items(args["paths"])) {
                string path=Convert.ToString(p);
                try {results.Add(new {path=path,value=OfficeGraph.Apply(chart,new Dictionary<string,object>{{"path",path}},true)});}
                catch(Exception e) {results.Add(new {path=path,unavailable=e.GetBaseException().Message});}
            }
            return results;
        }
        static object[,] Matrix(object input) {
            var rows=Items(input);
            if(rows.Count<2 || rows.Count>10001) throw new ArgumentException("Use a header and 1..10000 data rows.");
            int width=Items(rows[0]).Count;
            if(width<2 || width>128) throw new ArgumentException("Use 2..128 columns.");
            var values=new object[rows.Count,width];
            for(int i=0;i<rows.Count;i++) {
                var row=Items(rows[i]); if(row.Count!=width) throw new ArgumentException("Data rows have different lengths.");
                for(int j=0;j<width;j++) {
                    var cell=row[j];if(cell is string) {
                        string s=(string)cell; if(s.Length>32000) throw new ArgumentException("Cell text is too long.");
                        if(s.Length>0 && "=+-@\t\r".IndexOf(s[0])>=0) cell="'"+s;
                    } else if(cell!=null && !(cell is int) && !(cell is double) && !(cell is long) && !(cell is decimal) && !(cell is bool)) throw new ArgumentException("Scalar data cells required.");
                    values[i,j]=cell;
                }
            }
            return values;
        }
        static void Data(dynamic chart,object[,] values) {
            dynamic data=chart.ChartData;
            if((bool)data.IsLinked) throw new InvalidOperationException("Select an embedded chart. This chart links to an external workbook.");
            data.Activate();dynamic book=data.Workbook;bool ok=false;
            try {
                dynamic ws=book.Worksheets[1];
                if(Convert.ToDouble(ws.UsedRange.CountLarge)>2000000) throw new InvalidOperationException("Embedded data range is too large.");
                ws.UsedRange.ClearContents();
                dynamic area=ws.Range[ws.Cells[1,1],ws.Cells[values.GetLength(0),values.GetLength(1)]];
                area.Value2=values;
                string address=Convert.ToString(area.Address);
                chart.SetSourceData("='"+((string)ws.Name).Replace("'","''")+"'!"+address,2);
                ok=true;
            } finally {book.Close(ok);}
            chart.Refresh();
        }
        public static object Change(dynamic deck,string workspace,string op,Dictionary<string,object> args) {
            if(op=="insert_draft") {
                string p=Draft(workspace,Str(args,"filename"),false);
                int after=Num(args,"after",(int)deck.Slides.Count);
                int inserted=(int)deck.Slides.InsertFromFile(p,after);
                return new {inserted=inserted,after=after};
            }
            if(op=="chart_add") {
                int type=Num(args,"type",51);
                int version=Int32.Parse(((string)deck.Application.Version).Split('.')[0]);
                if((type>=117 || type==-2) && version<16) throw new NotSupportedException("This chart type requires a modern PowerPoint build.");
                if(type==-2 || type==-4152 || type==116) throw new NotSupportedException("Specify the actual chart or compose a named combination.");
                dynamic slide=Slide(deck,args);
                float x=Pos(args,"left",40),y=Pos(args,"top",65),w=Pos(args,"width",500),h=Pos(args,"height",300);
                var values=Matrix(args["rows"]);
                dynamic sh=null;
                try {
                    if(type>=117) sh=slide.Shapes.AddChart2(-1,type,x,y,w,h,true);
                    else sh=slide.Shapes.AddChart(51,x,y,w,h);
                    dynamic c=sh.Chart; Data(c,values);
                    if((int)c.ChartType!=type) c.ChartType=type;
                    if((int)c.ChartType!=type || (bool)c.ChartData.IsLinked) throw new InvalidOperationException("The requested embedded chart type was not retained.");
                    return new {shapeId=(int)sh.Id,type=(int)c.ChartType,embedded=true};
                } catch {if(sh!=null) sh.Delete();throw;}
            }
            if(op=="chart_data") {Data(Chart(deck,args),Matrix(args["rows"]));return new {updated=true};}
            if(op=="chart_patch") {
                object chart=Chart(deck,args);var edits=Items(args["edits"]); if(edits.Count<1 || edits.Count>200) throw new ArgumentException("Use 1..200 chart edits.");
                int i=0;
                try {foreach(var edit in edits) {OfficeGraph.Apply(chart,(Dictionary<string,object>)edit,false);i++;}}
                catch(Exception e){throw new InvalidOperationException("Applied "+i+" edits. Failed at "+i+": "+e.GetBaseException().Message);}
                return new {applied=i};
            }
            if(op!="slide_edit") throw new ArgumentException("Unknown operation.");
            string action=Str(args,"action");
            if(action=="add_slide"){
                dynamic s=deck.Slides.Add(Num(args,"index",(int)deck.Slides.Count+1),Num(args,"layout",12));
                return new {slideId=(int)s.SlideID};
            }
            dynamic slideObj=Slide(deck,args);
            switch(action) {
                case "duplicate_slide": dynamic dup=slideObj.Duplicate();return new {slideId=(int)dup[1].SlideID};
                case "move_slide": slideObj.MoveTo(Num(args,"index",1));return true;
                case "delete_slide": slideObj.Delete();return true;
                case "transition": slideObj.SlideShowTransition.EntryEffect=Num(args,"effect",0);return true;
                case "hidden": slideObj.SlideShowTransition.Hidden=(bool)args["value"]?-1:0;return true;
                case "notes":
                    foreach(dynamic holder in slideObj.NotesPage.Shapes.Placeholders) if((int)holder.PlaceholderFormat.Type==2){holder.TextFrame.TextRange.Text=Str(args,"text");return true;}
                    throw new InvalidOperationException("Notes body placeholder not available.");
                case "add_text":
                    dynamic box=slideObj.Shapes.AddTextbox(1,Pos(args,"left",40),Pos(args,"top",40),Pos(args,"width",400),Pos(args,"height",100));
                    try {box.TextFrame.TextRange.Text=Str(args,"text");return new {shapeId=(int)box.Id};} catch{box.Delete();throw;}
                case "add_shape":
                    dynamic shape=slideObj.Shapes.AddShape(Num(args,"type",1),Pos(args,"left",40),Pos(args,"top",40),Pos(args,"width",200),Pos(args,"height",80));
                    return new {shapeId=(int)shape.Id};
            }
            dynamic target=Shape(slideObj,Num(args,"shapeId",0));
            switch(action) {
                case "set_text": target.TextFrame.TextRange.Text=Str(args,"text");break;
                case "delete_shape": target.Delete();break;
                case "table_cell": target.Table.Cell(Num(args,"row",1),Num(args,"column",1)).Shape.TextFrame.TextRange.Text=Str(args,"text");break;
                case "geometry":
                    foreach(string p in new[]{"Left","Top","Width","Height","Rotation"}) if(args.ContainsKey(p.ToLowerInvariant()))
                        ((object)target).GetType().InvokeMember(p,System.Reflection.BindingFlags.SetProperty,null,(object)target,new object[]{Pos(args,p.ToLowerInvariant(),0)});
                    break;
                case "font":
                    dynamic tr=target.TextFrame.TextRange;
                    if(args.ContainsKey("start")) tr=tr.Characters(Num(args,"start",1),Num(args,"length",1));
                    if(args.ContainsKey("name")) tr.Font.Name=Str(args,"name");
                    if(args.ContainsKey("size")) tr.Font.Size=Pos(args,"size",18);
                    if(args.ContainsKey("bold")) tr.Font.Bold=(bool)args["bold"]?-1:0;
                    if(args.ContainsKey("rgb")) tr.Font.Color.RGB=Num(args,"rgb",0);
                    break;
                case "z_order": target.ZOrder(Num(args,"order",0));break;
                default: throw new ArgumentException("Unknown slide action.");
            }
            return true;
        }
    }
}
