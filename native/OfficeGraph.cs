using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text.RegularExpressions;

namespace SlidePilot {
    internal static class OfficeGraph {
        // Only chart/formatting children may be traversed. Navigation to applications,
        // workbooks, parents, hyperlinks and arbitrary Office methods is never exposed.
        internal const string Children="ChartArea PlotArea Legend LegendEntries LegendKey ChartTitle Axes AxisTitle MajorGridlines MinorGridlines TickLabels DisplayUnitLabel SeriesCollection FullSeriesCollection Points DataLabels DataLabel ChartGroups ChartGroup Trendlines Trendline ErrorBars DropLines HiLoLines UpBars DownBars SeriesLines Walls Floor SideWall BackWall Corners DataTable Format Fill Line ForeColor BackColor Color Font Border Interior Shadow Glow SoftEdge ThreeD TextFrame2 TextRange Font2 ParagraphFormat GradientStops GradientStop MarkerForegroundColorIndex ColorStops Characters LeaderLines";
        internal const string Writable="ChartType ChartStyle ChartColor HasTitle HasLegend HasDataTable HasAxis HasMajorGridlines HasMinorGridlines HasMajorUnit HasMinorUnit HasDisplayUnitLabel HasLeaderLines HasDataLabels HasErrorBars HasUpDownBars HasHiLoLines HasDropLines HasSeriesLines Has3DShading HasRadarAxisLabels HasDropLines Visible IncludeInLayout Position Left Top Width Height InsideLeft InsideTop InsideWidth InsideHeight AutoScaleFont AutoScaling AutoText ScaleType LogBase MinimumScale MinimumScaleIsAuto MaximumScale MaximumScaleIsAuto MajorUnit MajorUnitIsAuto MinorUnit MinorUnitIsAuto Crosses CrossesAt ReversePlotOrder AxisBetweenCategories CategoryType BaseUnit BaseUnitIsAuto MajorUnitScale MinorUnitScale MajorTickMark MinorTickMark TickLabelPosition TickLabelSpacing TickLabelSpacingIsAuto TickMarkSpacing Orientation Alignment ReadingOrder DisplayUnit DisplayUnitCustom NumberFormat NumberFormatLinked Text Caption Name Size Bold Italic Underline StrikeThrough RGB ObjectThemeColor TintAndShade Brightness Transparency Weight DashStyle Style BeginArrowheadStyle EndArrowheadStyle BeginArrowheadLength BeginArrowheadWidth EndArrowheadLength EndArrowheadWidth Pattern PatternColorIndex ColorIndex Color AxisGroup PlotOrder Smooth MarkerStyle MarkerSize MarkerBackgroundColor MarkerForegroundColor MarkerBackgroundColorIndex MarkerForegroundColorIndex Explosion GapWidth GapDepth Overlap DoughnutHoleSize FirstSliceAngle VaryByCategories BubbleScale SizeRepresents ShowNegativeBubbles SplitType SplitValue SecondPlotSize DisplayBlanksAs PlotVisibleOnly Rotation Elevation Perspective RightAngleAxes DepthPercent HeightPercent GapDepth WallsAndGridlines2D BarShape ShowLegendKey ShowValue ShowCategoryName ShowSeriesName ShowPercentage ShowBubbleSize ShowRange ShowLeaderLines Separator ShowMarkerKeys ShowHorizontalBorder ShowVerticalBorder ShowOutline BorderColor Direction Offset Blur Radius Angle Distance RotationX RotationY RotationZ Depth PresetLightingDirection PresetLightingSoftness BevelTopType BevelTopDepth BevelTopInset MarginLeft MarginRight MarginTop MarginBottom VerticalAnchor HorizontalAnchor WordWrap AutoSize SpacingWithin SpaceBefore SpaceAfter SpaceWithin FirstLineIndent LeftIndent HangingPunctuation LanguageID DisplayEquation DisplayRSquared Forward Backward Intercept InterceptIsAuto Order Period Type EndStyle ShowConnectorLines InvertIfNegative InvertColor InteriorColor HasInterior";
        internal const string Methods="Solid Patterned OneColorGradient TwoColorGradient PresetGradient ApplyDataLabels ErrorBar Add Delete ClearFormats";
        static HashSet<string> Set(string names) {return new HashSet<string>(names.Split(' '),StringComparer.Ordinal);}
        static readonly HashSet<string> child=Set(Children), writable=Set(Writable), methods=Set(Methods);
        static readonly Regex Segment=new Regex(@"^([A-Za-z][A-Za-z0-9]*)(?:\(([-0-9]+(?:,[-0-9]+)*)\))?$");
        static object Invoke(object target,string name,BindingFlags flags,object[] args) {
            try {return target.GetType().InvokeMember(name,flags|BindingFlags.OptionalParamBinding,null,target,args,CultureInfo.InvariantCulture);}
            catch(TargetInvocationException ex){throw ex.InnerException??ex;}
        }
        static object Hop(object current,string segment) {
            var m=Segment.Match(segment);
            if(!m.Success || !child.Contains(m.Groups[1].Value)) throw new ArgumentException("Unknown chart child: "+segment);
            object[] args=m.Groups[2].Success?Array.ConvertAll(m.Groups[2].Value.Split(','),x=>(object)Int32.Parse(x,CultureInfo.InvariantCulture)):new object[0];
            return Invoke(current,m.Groups[1].Value,BindingFlags.GetProperty|BindingFlags.InvokeMethod,args);
        }
        static object Scalar(object value) {
            if(value==null || value is string || value is bool || value is int || value is long || value is double || value is decimal) return value;
            throw new ArgumentException("A scalar property value is required.");
        }
        public static object Apply(object chart,Dictionary<string,object> op,bool read) {
            string path=Convert.ToString(op["path"]);
            var pieces=path.Split('.');
            if(pieces.Length>14 || path.Length>350) throw new ArgumentException("Chart path is too deep.");
            object obj=chart;
            for(int i=0;i<pieces.Length-1;i++) obj=Hop(obj,pieces[i]);
            string key=pieces[pieces.Length-1];
            if(read) {
                if(!writable.Contains(key) && key!="Count" && key!="Index") throw new ArgumentException("Unknown readable property: "+key);
                object result=Invoke(obj,key,BindingFlags.GetProperty,new object[0]);
                if(result!=null && System.Runtime.InteropServices.Marshal.IsComObject(result)) throw new ArgumentException("Select a scalar child of "+key);
                return result;
            }
            if(op.ContainsKey("value")) {
                if(!writable.Contains(key)) throw new ArgumentException("Unknown writable property: "+key);
                if(key=="Name" && pieces.Length>1 && pieces[pieces.Length-2].StartsWith("SeriesCollection") && Convert.ToString(op["value"]).StartsWith("="))
                    throw new ArgumentException("Use a literal series name.");
                Invoke(obj,key,BindingFlags.SetProperty,new[]{Scalar(op["value"])});
            } else {
                if(!methods.Contains(key)) throw new ArgumentException("Unknown chart action: "+key);
                if(key=="Delete" && (pieces.Length<2 || !Regex.IsMatch(pieces[pieces.Length-2],@"^(Trendlines|DataLabels|LegendEntries)\(\d+\)$")))
                    throw new ArgumentException("Delete requires an indexed trendline, label or legend entry.");
                if(key=="Add" && (pieces.Length<2 || pieces[pieces.Length-2]!="Trendlines")) throw new ArgumentException("Add is limited to trendlines.");
                var args=new List<object>();
                object raw;
                if(op.TryGetValue("args",out raw)) foreach(var a in (IEnumerable)raw) args.Add(Scalar(a));
                Invoke(obj,key,BindingFlags.InvokeMethod,args.ToArray());
            }
            return true;
        }
    }
}
