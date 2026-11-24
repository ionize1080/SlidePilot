using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using SlidePilot;
public class FakeSeries { public string Name { get; set; } }
public class FakeChart {
    readonly bool[,] axes=new bool[4,3];
    readonly FakeSeries series=new FakeSeries();
    [IndexerName("HasAxis")]
    public bool this[int axis,int group] { get {return axes[axis,group];} set {axes[axis,group]=value;} }
    public FakeSeries SeriesCollection(int index){return series;}
    public FakeSeries FullSeriesCollection(int index){return series;}
    public double Rotation {get;set;}
}
class NativeRegression {
    static Dictionary<string,object> Op(string path,object value){return new Dictionary<string,object>{{"path",path},{"value",value}};}
    static void Reject(Action action){try{action();throw new Exception("Expected rejection");}catch(ArgumentException){}}
    static int Main(){
        var chart=new FakeChart();
        OfficeGraph.Apply(chart,Op("HasAxis(2,1)",true),false);
        if(!(bool)OfficeGraph.Apply(chart,new Dictionary<string,object>{{"path","HasAxis(2,1)"}},true)) throw new Exception("Axis property not updated");
        Reject(()=>OfficeGraph.Apply(chart,Op("HasAxis(4,1)",true),false));
        Reject(()=>OfficeGraph.Apply(chart,Op("Rotation(1)",4),false));
        Reject(()=>OfficeGraph.Apply(chart,Op("Rotation",Double.NaN),false));
        Reject(()=>OfficeGraph.Apply(chart,Op("SeriesCollection(1).Name","=external!A1"),false));
        Reject(()=>OfficeGraph.Apply(chart,Op("FullSeriesCollection(1).Name","  =external!A1"),false));
        OfficeGraph.Apply(chart,Op("FullSeriesCollection(1).Name","Retail"),false);
        if(chart.FullSeriesCollection(1).Name!="Retail")throw new Exception("Series name not updated");
        var matrix=typeof(Live).GetMethod("Matrix",BindingFlags.Static|BindingFlags.NonPublic);
        var values=(object[,])matrix.Invoke(null,new object[]{new object[]{new object[]{"Category","Value"},new object[]{"=formula",4}}});
        if((string)values[1,0]!="'=formula")throw new Exception("Formula literal changed");
        bool rejected=false;
        try{matrix.Invoke(null,new object[]{new object[]{new object[]{"Category","Value"},new object[]{"A",Double.PositiveInfinity}}});}
        catch(TargetInvocationException e){rejected=e.InnerException is ArgumentException;}
        if(!rejected)throw new Exception("Infinity accepted");
        Console.WriteLine("9 native chart regression checks passed.");
        return 0;
    }
}
