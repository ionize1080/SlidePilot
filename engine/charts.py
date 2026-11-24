"""Native DrawingML charts. Every chart includes formula-backed caches and a private XLSX."""
import re
from package_xml import tag, xml, column, workbook, numeric
from chart_types import TYPES, canonical

PALETTE = ["19636C","D48240","657AAB","8A525F","68855D","997C39"]


def color(value):
    s = str(value).lstrip("#").upper()
    if not re.fullmatch("[0-9A-F]{6}",s):
        raise ValueError("Expected a six-digit RGB color")
    return s


def solid(parent, value):
    tag("a:srgbClr",tag("a:solidFill",parent),val=color(value))


def cv(parent, name, value):
    return tag("c:"+name,parent,val=value)


def title(parent, value):
    t = tag("c:title",parent)
    rich = tag("c:rich",tag("c:tx",t))
    tag("a:bodyPr",rich)
    tag("a:lstStyle",rich)
    run = tag("a:r",tag("a:p",rich))
    tag("a:rPr",run,lang="en-US")
    tag("a:t",run,text=value)
    cv(t,"overlay",0)


def reference(parent, field, vals, ci, numeric_cache=False, header=False, fmt="General"):
    cell = column(ci)
    formula = "Data!$%s$1"%cell if header else "Data!$%s$2:$%s$%s"%(cell,cell,len(vals)+1)
    prefix = "num" if numeric_cache else "str"
    ref = tag("c:"+prefix+"Ref",tag("c:"+field,parent))
    tag("c:f",ref,text=formula)
    cache = tag("c:"+prefix+"Cache",ref)
    if numeric_cache:
        tag("c:formatCode",cache,text=fmt)
    cv(cache,"ptCount",len(vals))
    for i,v in enumerate(vals):
        if v is not None:
            tag("c:v",tag("c:pt",cache,idx=i),text=v)


def chart_group(name):
    family = TYPES[name][1]
    n = name[2:]
    if n in ("PieOfPie","BarOfPie"):
        return "ofPieChart"
    if family == "surface":
        return "surfaceChart" if "TopView" in n else "surface3DChart"
    if family == "ring":
        return "doughnutChart"
    is3d = n.startswith(("3D","Cone","Cylinder","Pyramid"))
    return family+("3D" if is3d else "")+"Chart"


def add_axis(pa, aid, other, kind, pos, opts, fmt):
    a = tag("c:"+kind+"Ax",pa)
    cv(a,"axId",aid)
    scale = tag("c:scaling",a)
    if "logBase" in opts: cv(scale,"logBase",opts["logBase"])
    cv(scale,"orientation","maxMin" if opts.get("reverse") else "minMax")
    for key in ("max","min"):
        if key in opts: cv(scale,key,opts[key])
    cv(a,"delete",int(bool(opts.get("hidden"))))
    cv(a,"axPos",opts.get("position",pos))
    if opts.get("gridlines",kind=="val" and pos=="l"):
        grid = tag("c:majorGridlines",a)
        solid(tag("a:ln",tag("c:spPr",grid)),opts.get("gridColor","DDE5E6"))
    if opts.get("minorGridlines"):
        tag("c:minorGridlines",a)
    if opts.get("title"): title(a,opts["title"])
    tag("c:numFmt",a,formatCode=opts.get("numberFormat",fmt if kind=="val" else "General"),sourceLinked=0)
    cv(a,"majorTickMark",opts.get("majorTick","none"))
    cv(a,"minorTickMark",opts.get("minorTick","none"))
    cv(a,"tickLblPos",opts.get("tickLabels","nextTo"))
    cv(a,"crossAx",other)
    if "crossesAt" in opts: cv(a,"crossesAt",opts["crossesAt"])
    else: cv(a,"crosses","max" if pos in ("r","t") else "autoZero")
    if kind=="cat":
        cv(a,"auto",1)
        cv(a,"lblAlgn","ctr")
        cv(a,"lblOffset",100)
    if kind=="val":
        cv(a,"crossBetween","between")
        for key in ("majorUnit","minorUnit"):
            if key in opts: cv(a,key,opts[key])


def build(spec):
    name = canonical(spec.get("type","xlColumnClustered"))
    family = TYPES[name][1]
    if family in ("modern","recommended"):
        raise ValueError(name+" requires live_chart_add on a verified modern host; do not substitute another chart.")
    series = spec.get("series",[])
    if not 1 <= len(series) <= 64:
        raise ValueError("A chart requires 1 to 64 series")
    default_cats = spec.get("categories",[])
    fmt = spec.get("numberFormat","General")
    columns, meta = [], []
    xy = family in ("scatter","bubble")
    if not xy:
        if not isinstance(default_cats,list) or not 1 <= len(default_cats) <= 10000:
            raise ValueError("Provide 1 to 10000 categories")
        if any(not isinstance(v,(str,int,float)) for v in default_cats):
            raise ValueError("Use scalar categories")
        columns.append([spec.get("categoryTitle","Category"),*default_cats])
    if family in ("pie",) and len(series)!=1:
        raise ValueError("Pie charts require one series")
    if family=="stock":
        count = {"xlStockHLC":3,"xlStockOHLC":4,"xlStockVHLC":4,"xlStockVOHLC":5}[name]
        if len(series)!=count: raise ValueError(name+" needs "+str(count)+" ordered series")
    for i,s in enumerate(series):
        values = s["values"]
        if not isinstance(values,list) or not 1 <= len(values) <= 10000 or any(v is not None and not numeric(v) for v in values):
            raise ValueError("Series values must be finite numbers or null")
        cat = s.get("x",default_cats) if xy else default_cats
        if len(cat)!=len(values) or (xy and not all(numeric(v) for v in cat)):
            raise ValueError("Category or numeric X count must match the series")
        if xy: columns.append([s.get("xName","X"),*cat])
        ci = len(columns)+1
        columns.append([s["name"],*values])
        meta.append((s,ci,cat))
        if family=="bubble":
            sizes = s.get("sizes",[])
            if len(sizes)!=len(values) or not all(numeric(v) and v>=0 for v in sizes):
                raise ValueError("Bubble sizes must match the series, with nonnegative numbers")
            columns.append([s["name"]+" size",*sizes])
    rows = [[col[r] if r<len(col) else None for col in columns] for r in range(max(map(len,columns)))]
    drawing = tag("c:chartSpace")
    cv(drawing,"lang","en-US")
    if "style" in spec:
        if type(spec["style"])!=int or not 1<=spec["style"]<=48: raise ValueError("Classic style range is 1..48")
        cv(drawing,"style",spec["style"])
    chart = tag("c:chart",drawing)
    if spec.get("title"): title(chart,spec["title"])
    cv(chart,"autoTitleDeleted",int(not bool(spec.get("title"))))
    is3d = "3D" in chart_group(name) or family=="surface"
    if is3d:
        view = tag("c:view3D",chart)
        for k,v in (("rotX",spec.get("rotationX",90 if "TopView" in name else 15)),
                    ("rotY",spec.get("rotationY",0 if "TopView" in name else 20)),("rAngAx",1)):
            cv(view,k,v)
    plot = tag("c:plotArea",chart)
    tag("c:layout",plot)
    buckets = {}
    for i,(s,ci,cats) in enumerate(meta):
        typ, axis = name, 1
        if family=="combo":
            default = ("xlAreaStacked" if i==0 else "xlColumnClustered") if name=="xlComboAreaStackedColumnClustered" else ("xlColumnClustered" if i==0 else "xlLine")
            typ = canonical(s.get("type",default))
            axis = s.get("axis",2 if i>0 and name.endswith("SecondaryAxis") else 1)
            if TYPES[typ][1] not in ("bar","line","area") or "3D" in chart_group(typ) or axis not in (1,2):
                raise ValueError("Use 2D bar/column, area or line for a combo, axis 1 or 2")
        if family=="stock" and "StockV" in name:
            typ,axis = ("xlColumnClustered",1) if i==0 else (name,2)
        buckets.setdefault((typ,axis),[]).append(i)
    if family=="combo" and len(buckets)<2:
        raise ValueError("A combination requires at least two distinct groups")
    axes={}
    for (typ,axis),indexes in buckets.items():
        group = chart_group(typ)
        kind = TYPES[typ][1]
        g = tag("c:"+group,plot)
        if kind=="bar":
            cv(g,"barDir","bar" if "Bar" in typ else "col")
        if kind in ("bar","line","area"):
            cv(g,"grouping","percentStacked" if "100" in typ else "stacked" if "Stacked" in typ else
               "clustered" if kind=="bar" and ("Clustered" in typ) else "standard")
        if group=="ofPieChart": cv(g,"ofPieType","bar" if typ=="xlBarOfPie" else "pie")
        if kind=="scatter":
            cv(g,"scatterStyle",{"xlXYScatter":"marker","xlXYScatterLines":"lineMarker","xlXYScatterLinesNoMarkers":"line",
                                 "xlXYScatterSmooth":"smoothMarker","xlXYScatterSmoothNoMarkers":"smooth"}[typ])
        if kind=="radar": cv(g,"radarStyle","filled" if "Filled" in typ else "marker" if "Markers" in typ else "standard")
        if kind=="surface": cv(g,"wireframe",int("Wireframe" in typ))
        if kind not in ("surface","stock"): cv(g,"varyColors",int(spec.get("varyColors",kind in ("pie","ring"))))
        for i in indexes:
            s,ci,cats=meta[i]
            ser=tag("c:ser",g)
            cv(ser,"idx",i)
            cv(ser,"order",i)
            reference(ser,"tx",[s["name"]],ci,header=True)
            series_color=s.get("color",PALETTE[i%len(PALETTE)])
            if "color" in s or kind not in ("pie","ring","stock","surface"):
                sp=tag("c:spPr",ser)
                if kind in ("line","scatter","radar") and "Filled" not in typ:
                    ln=tag("a:ln",sp,w=round(float(s.get("lineWidth",2))*12700))
                    if kind=="scatter" and typ=="xlXYScatter": tag("a:noFill",ln)
                    else: solid(ln,series_color)
                else: solid(sp,series_color)
            if kind in ("line","scatter","radar") and group!="line3DChart" or "marker" in s and kind=="line":
                mark=tag("c:marker",ser)
                cv(mark,"symbol",s.get("marker","circle" if "Markers" in typ and "NoMarkers" not in typ or kind=="scatter" and "NoMarkers" not in typ else "none"))
                cv(mark,"size",int(s.get("markerSize",6)))
            if kind in ("pie","ring") and ("Exploded" in typ or "explosion" in s): cv(ser,"explosion",s.get("explosion",15))
            for point in s.get("points",[]):
                if not 0<=point["index"]<len(s["values"]): raise ValueError("Point index is out of range")
                dp=tag("c:dPt",ser)
                cv(dp,"idx",point["index"])
                if "explosion" in point: cv(dp,"explosion",point["explosion"])
                if "color" in point: solid(tag("c:spPr",dp),point["color"])
            if kind=="surface" and s.get("points"): raise ValueError("Surface series do not accept per-point styling")
            if xy:
                reference(ser,"xVal",cats,ci-1,True)
                reference(ser,"yVal",s["values"],ci,True,fmt=fmt)
                if family=="bubble":
                    reference(ser,"bubbleSize",s["sizes"],ci+1,True)
                    cv(ser,"bubble3D",int(typ=="xlBubble3DEffect"))
            else:
                reference(ser,"cat",cats,1,all(numeric(v) for v in cats))
                reference(ser,"val",s["values"],ci,True,fmt=fmt)
            if kind in ("line","scatter") and ("smooth" in s or "Smooth" in typ):
                cv(ser,"smooth",int(s.get("smooth",True)))
        if spec.get("labels") and kind!="surface":
            labels=tag("c:dLbls",g)
            opt=spec["labels"] if isinstance(spec["labels"],dict) else {"value":True}
            if "position" in opt: cv(labels,"dLblPos",opt["position"])
            for key,xmlname in (("legendKey","showLegendKey"),("value","showVal"),("category","showCatName"),("series","showSerName"),("percent","showPercent"),("bubbleSize","showBubbleSize")):
                cv(labels,xmlname,int(opt.get(key,False)))
        if kind=="bar":
            cv(g,"gapWidth",spec.get("gapWidth",125))
            if group=="barChart": cv(g,"overlap",spec.get("overlap",100 if "Stacked" in typ else 0))
            else:
                cv(g,"gapDepth",spec.get("gapDepth",150))
                cv(g,"shape",next((x for x in ("cone","cylinder","pyramid") if x in typ.lower()),"box"))
        if kind=="ring":
            cv(g,"firstSliceAng",spec.get("firstSliceAngle",0))
            cv(g,"holeSize",spec.get("holeSize",55))
        if group=="pieChart": cv(g,"firstSliceAng",spec.get("firstSliceAngle",0))
        if kind=="bubble": cv(g,"bubbleScale",spec.get("bubbleScale",100))
        if kind=="stock":
            tag("c:hiLowLines",g)
            if "OHLC" in typ:
                bars=tag("c:upDownBars",g)
                cv(bars,"gapWidth",150)
                tag("c:upBars",bars)
                tag("c:downBars",bars)
        if kind not in ("pie","ring"):
            aid=1000*axis
            depth=kind=="surface" or group in ("area3DChart","line3DChart") or typ in ("xl3DColumn","xlCylinderCol","xlConeCol","xlPyramidCol")
            for ax in [aid+1,aid+2]+([aid+3] if depth else []): cv(g,"axId",ax)
            axes[axis]=(xy,depth)
    for a,(isxy,depth) in axes.items():
        aid=1000*a
        add_axis(plot,aid+1,aid+2,"val" if isxy else "cat","b" if a==1 else "t",spec.get("xAxis" if a==1 else "secondaryXAxis",{}),fmt)
        add_axis(plot,aid+2,aid+1,"val","l" if a==1 else "r",spec.get("yAxis" if a==1 else "secondaryYAxis",{}),fmt)
        if depth: add_axis(plot,aid+3,aid+1,"ser","b",{},fmt)
    if spec.get("plotColor"): solid(tag("c:spPr",plot),spec["plotColor"])
    if spec.get("legend",len(series)>1):
        leg=tag("c:legend",chart)
        cv(leg,"legendPos",spec.get("legendPosition","b"))
        cv(leg,"overlay",0)
    cv(chart,"plotVisOnly",1)
    cv(chart,"dispBlanksAs",spec.get("blanks","gap"))
    if spec.get("background"): solid(tag("c:spPr",drawing),spec["background"])
    text=tag("c:txPr",drawing)
    tag("a:bodyPr",text)
    tag("a:lstStyle",text)
    font=tag("a:defRPr",tag("a:pPr",tag("a:p",text)),sz=1300)
    tag("a:latin",font,typeface="Calibri")
    tag("a:ea",font,typeface="Microsoft YaHei")
    cv(tag("c:externalData",drawing,**{"r:id":"rIdBook"}),"autoUpdate",0)
    return xml(drawing),workbook(rows,[fmt] if fmt!="General" else [])
