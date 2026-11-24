"""Office XlChartType values, with compatibility and concrete input requirements."""
GROUPS = {
    "area": {"Area":1,"AreaStacked":76,"AreaStacked100":77,"3DArea":-4098,"3DAreaStacked":78,"3DAreaStacked100":79},
    "bar": {"ColumnClustered":51,"ColumnStacked":52,"ColumnStacked100":53,"3DColumnClustered":54,"3DColumnStacked":55,
            "3DColumnStacked100":56,"3DColumn":-4100,"BarClustered":57,"BarStacked":58,"BarStacked100":59,
            "3DBarClustered":60,"3DBarStacked":61,"3DBarStacked100":62},
    "line":{"Line":4,"LineStacked":63,"LineStacked100":64,"LineMarkers":65,"LineMarkersStacked":66,"LineMarkersStacked100":67,"3DLine":-4101},
    "pie":{"Pie":5,"3DPie":-4102,"PieExploded":69,"3DPieExploded":70,"PieOfPie":68,"BarOfPie":71},
    "ring":{"Doughnut":-4120,"DoughnutExploded":80},
    "scatter":{"XYScatter":-4169,"XYScatterSmooth":72,"XYScatterSmoothNoMarkers":73,"XYScatterLines":74,"XYScatterLinesNoMarkers":75},
    "bubble":{"Bubble":15,"Bubble3DEffect":87},
    "stock":{"StockHLC":88,"StockOHLC":89,"StockVHLC":90,"StockVOHLC":91},
    "radar":{"Radar":-4151,"RadarMarkers":81,"RadarFilled":82},
    "surface":{"Surface":83,"SurfaceWireframe":84,"SurfaceTopView":85,"SurfaceTopViewWireframe":86},
    "combo":{"Combo":-4152,"ComboColumnClusteredLine":113,"ComboColumnClusteredLineSecondaryAxis":114,
             "ComboAreaStackedColumnClustered":115,"OtherCombinations":116},
    "modern":{"Treemap":117,"Histogram":118,"Waterfall":119,"Sunburst":120,"Boxwhisker":121,"Pareto":122,"Funnel":123,
              "ColumnClusteredEx":124,"ColumnStackedEx":125,"ColumnStacked100Ex":126,"LineEx":127,"LineStackedEx":128,
              "LineStacked100Ex":129,"PieEx":130,"DoughnutEx":131,"BarClusteredEx":132,"BarStackedEx":133,"BarStacked100Ex":134,
              "AreaEx":135,"AreaStackedEx":136,"AreaStacked100Ex":137,"XYScatterEx":138,"BubbleEx":139,"RegionMap":140},
    "recommended":{"SuggestedChart":-2},
}
for group, start in [("Cylinder",92),("Cone",99),("Pyramid",106)]:
    for i, suffix in enumerate(("ColClustered","ColStacked","ColStacked100","BarClustered","BarStacked","BarStacked100","Col")):
        GROUPS["bar"][group+suffix] = start+i
TYPES = {"xl"+n:(v,g) for g,items in GROUPS.items() for n,v in items.items()}
BY_ID = {v:k for k,(v,_) in TYPES.items()}


def canonical(value):
    if type(value) is int:
        value = BY_ID.get(value)
    if isinstance(value,str):
        val = value.removeprefix("xl").casefold()
        for key in TYPES:
            if key[2:].casefold() == val:
                return key
    raise ValueError("Unknown chart type. Use chart_catalog for exact names.")


def catalogue():
    return [{"type":k,"value":v,"family":g,
             "route":"recommendation_only" if g=="recommended" else "live_probe" if g=="modern" else "embedded_ooxml",
             "guidance":("PowerPoint 16+ feature probe via live_chart_add. May vary by build, license and data."
                         if g=="modern" else "Host recommendation, not a persistable chart type." if g=="recommended"
                         else "One stock series per column in the named order." if g=="stock"
                         else "Use numeric X coordinates and values; bubbles also require sizes." if g in ("scatter","bubble")
                         else "Supply at least two groups/series; secondary axes are explicit." if g=="combo"
                         else "Provide categories and named series with matching lengths.")}
            for k,(v,g) in TYPES.items()]
