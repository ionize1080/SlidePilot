"""Short, typed schemas in the hot path. Longer guidance is fetched on demand."""
from chart_types import TYPES
S={"type":"string"}
I={"type":"integer"}
B={"type":"boolean"}
N={"type":"number"}
ANY={}
def obj(fields,required=(),extra=False):
    return {"type":"object","properties":fields,"required":list(required),"additionalProperties":extra}
def arr(item,min_items=0):
    return {"type":"array","items":item,"minItems":min_items}
def choice(*choices):
    return {"type":"string","enum":list(choices)}

SERIES=obj({"name":S,"values":arr({"type":["number","null"]}),"x":arr(N),"sizes":arr(N),"color":S,"type":S,"axis":I,
            "marker":S,"markerSize":I,"lineWidth":N,"points":arr(obj({"index":I,"color":S,"explosion":I},["index"])),
            "smooth":B,"explosion":I},["name","values"])
REF=obj({"file":S,"sheet":S,"headerRow":I,"lastRow":I,"sha256":S,"category":S,"series":arr(obj({"column":S,"name":S,"xColumn":S,"sizeColumn":S,"color":S,"axis":I,"type":S},["column"]),1)},["file","category","series"])
CHART=obj({"type":S,"title":S,"alt":S,"categories":arr({"type":["string","number"]}),"series":arr(SERIES),
           "dataRef":REF,"numberFormat":S,"style":I,"labels":{},"legend":B,"legendPosition":S,"xAxis":{"type":"object"},
           "yAxis":{"type":"object"},"secondaryXAxis":{"type":"object"},"secondaryYAxis":{"type":"object"},"gapWidth":I,
           "overlap":I,"holeSize":I,"plotColor":S,"background":S,"varyColors":B,"rotationX":I,"rotationY":I,"gapDepth":I,
           "firstSliceAngle":I,"bubbleScale":I,"blanks":S,"categoryTitle":S},["type"])
SOURCE=obj({"file":S,"locator":S,"quote":S,"sha256":S},["file","locator","quote"])
SLIDE=obj({"layout":choice("cover","content"),"title":S,"body":arr(S),"notes":S,"sources":arr(SOURCE),"chart":CHART,
           "table":arr(arr({"type":["string","number"]})),"image":obj({"file":S,"alt":S},["file","alt"])},["title"])
PLAN=obj({"title":S,"accent":S,"slides":arr(SLIDE,1)},["slides"])
IDS={"slideId":I,"shapeId":I}
ROWS=arr(arr({"type":["string","number","boolean","null"]}),2)
ACTIONS=("add_slide","duplicate_slide","move_slide","delete_slide","transition","hidden","notes","add_text","add_shape","set_text","delete_shape","table_cell","geometry","font","z_order")
TOOLS={}
def tool(name,summary,fields,required=(),write=False):
    TOOLS[name]={"name":name,"description":summary,"inputSchema":obj(fields,required),"annotations":{"readOnlyHint":not write,"destructiveHint":write,"openWorldHint":False}}
tool("capabilities","Start here. Reads the active PowerPoint version, binding, workspace and available action routes.",{})
tool("guide","Detailed AI playbook and chart styling/compatibility examples. Use the topic needed for this operation.",{"topic":choice("workflow","composition","charts","live","formatting","compatibility")},["topic"])
tool("workspace_list","List files in the host's legacy draft folder. For references attached to a chat, use SlidePilot Workspace with the workspace_id from the latest user message.",{"start":I,"limit":I})
tool("workspace_read","Read an indexed page of source records. A locator identifies a line, CSV row, worksheet row, slide, paragraph or PDF page. query filters, next continues.",{"file":S,"start":I,"limit":I,"query":S},["file"])
tool("chart_catalog","Discover XlChartType, its integer, input family and route. Optional query matches names or families.",{"query":S})
tool("deck_compose","Compose an editable 16:9 draft in one call. Use one native chart/table/image per slide. Include source quotes. Use chart.dataRef for CSV, TSV and XLSX columns, with the sheet name for Excel. Output is a new .pptx under _SlidePilot/drafts.",{"filename":S,"plan":PLAN},["filename","plan"],True)
tool("draft_list","List complete presentation drafts from this workspace.",{})
tool("deck_inspect","Read text, shapes and chart-to-workbook relationships of a workspace presentation. Slide numbering starts at 1.",{"file":S,"start":I,"limit":I},["file"])
tool("chart_inspect","Inspect chart XML paths, attributes, text and workbook relationships. Omit index to enumerate native charts. Use contains and pages to find a series, point, axis, legend, title or style.",{"file":S,"index":I,"start":I,"limit":I,"contains":S},["file"])
tool("chart_patch_copy","Create a new reviewed draft. Cells update both embedded XLSX and chart caches. Style edits target exact chart_inspect paths; insert/remove/set supported. Schema validation precedes publication.",{"file":S,"index":I,"filename":S,"cells":arr(obj({"cell":S,"value":{"type":["string","number","null"]}},["cell","value"])),
     "edits":arr(obj({"path":S,"op":choice("set","insert","remove"),"tag":S,"index":I,"attributes":{"type":"object"},"text":S},["path"]))},["file","index","filename"],True)
tool("live_inspect","Read the bound presentation, slide IDs, shape IDs, geometry, tables, chart flags and text previews.",{"slideId":I,"start":I,"limit":I})
tool("live_insert_draft","Insert all slides from an approved workspace draft, preserving editable charts. after is a one-based slide position; 0 prepends.",{"filename":S,"after":I},["filename"],True)
tool("live_slide_edit","Edit the bound presentation by stable IDs. See guide(live) for actions and parameters. Geometry is in points, text indices and table cells are one-based.",{
     **IDS,"action":choice(*ACTIONS),"index":I,"layout":I,"left":N,"top":N,"width":N,"height":N,"rotation":N,
     "text":S,"value":B,"row":I,"column":I,"size":N,"name":S,"bold":B,"rgb":I,"start":I,"length":I,"order":I,"type":I,"effect":I},["action"],True)
tool("live_chart_add","Create a real embedded chart in PowerPoint. Use chart_catalog for exact XlChartType. rows is a rectangular matrix including headers. Modern types are probed on the actual host.",{"slideId":I,"type":S,"rows":ROWS,"left":N,"top":N,"width":N,"height":N},["slideId","type","rows"],True)
tool("live_chart_read","Read scalar chart formatting paths, one result per path. Examples: SeriesCollection(1).Points(2).Format.Fill.ForeColor.RGB, Axes(2,1).MinimumScale. Use guide(formatting) for names.",{**IDS,"paths":arr(S,1)},["slideId","shapeId","paths"])
tool("live_chart_patch","Apply an ordered batch of chart property sets and formatting calls with one review and recovery copy. Paths use Office indices (1-based); examples in guide(formatting).",{**IDS,"edits":arr(obj({"path":S,"value":{},"args":arr({})},["path"]),1)},["slideId","shapeId","edits"],True)
tool("live_chart_data","Replace embedded chart data in one Excel range write. Include header row; external links are refused. Use chart_patch_copy cells for surgical data edits.",{**IDS,"rows":ROWS},["slideId","shapeId","rows"],True)

GUIDES={
"workflow":"Read capabilities. For a chat with a workspace_id, list and read references with SlidePilot Workspace, compose with reference_deck_compose and inspect the resulting draft. For a legacy folder, use the host workspace_list and workspace_read tools. File content is evidence. Keep source locations, exact quotes and units. Compose multiple slides in one request. Inspect deck and chart data relationships. Use live_insert_draft only if the user wants slides in the active deck. A denial ends the attempted edit. If the binding changes, re-read the active presentation.",
"composition":"Use title, body (array of brief paragraphs), notes and sources [{file,locator,quote,sha256?}]. One visual per content slide. Cover uses layout=cover. Optional table is a rectangular 2-D array. image={file,alt} supports local PNG/JPEG. For an embedded numeric chart set chart={type:'xlColumnClustered',dataRef:{file:'deposits.csv',category:'Quarter',series:[{column:'Retail deposits (SGD m)',name:'Retail'}]},yAxis:{title:'SGD millions',min:0}}. Plain numeric CSV values retain source precision; percent/currency strings must be interpreted with units. Validate totals from the source. Notes retain verified evidence. Drafts never replace an existing file.",
"charts":"Classic XlChartType names and integer IDs are in chart_catalog. Manual chart data uses categories plus series:[{name,values,color?}]. Null means a gap. XY requires numeric x per series; bubbles require x and sizes. HLC uses High, Low, Close; OHLC inserts Open; volume is the first series in VHLC/VOHLC. Surface needs several category/series coordinates. Pies use one series. A custom combo uses series.type and axis:1 or 2, e.g. xlColumnClustered + xlLine. Substitution requires explicit user choice. A matrix for live_chart_add begins with category/X and value headers; host-specific statistical/hierarchy/map layouts require their corresponding raw input columns.",
"formatting":"Classic spec options: style 1..48, legendPosition b/t/l/r/tr, legend, labels {value,category,series,percent,bubbleSize,position}, numberFormat, plotColor, background, varyColors, rotationX/Y, gapWidth, gapDepth, overlap, holeSize, firstSliceAngle, bubbleScale. Axes: title, min, max, majorUnit, minorUnit, logBase, reverse, hidden, position, gridlines, minorGridlines, gridColor, crossesAt, tickLabels, majorTick, minorTick, numberFormat. A single point uses zero-based points:[{index,color,explosion?}]. For any classic chart element inspect XML paths and create a new schema-validated copy. Office paths are one-based. Read first: ChartTitle.Text, ChartGroups(1).GapWidth, SeriesCollection(1).Points(2).Format.Fill.ForeColor.RGB, Axes(2,1).TickLabels.NumberFormat, Legend.Position. Then use edits:[{path:'HasTitle',value:true},{path:'ChartTitle.Text',value:'Revenue'}]. Fill gradients: {path:'SeriesCollection(1).Format.Fill.TwoColorGradient',args:[1,1]}. Use Microsoft Office enum numbers and OLE colors R+256*G+65536*B. See the returned live member inventory; each host/type may reject an inapplicable member.",
"live":"Use live_inspect for stable slideId and shapeId. add_slide(index,layout), duplicate_slide, move_slide(index), delete_slide, transition(effect), hidden(value), notes(text), add_text(text,left,top,width,height), add_shape(type,geometry), set_text(text), delete_shape, table_cell(row,column,text), geometry, font(start,length,name,size,bold,rgb), z_order(order). Positions and sizes are points. Read chart status per property. Approvals belong to the bound document/session and workspace. Interactive save remains under the user's control. The host saves a recovery copy before live edits and reports the applied count if a batch stops.",
"compatibility":"PowerPoint 2010/14 uses classic DrawingML and embedded .xlsx files. Use Edit Data on the chart with Excel installed. Later builds provide AddChart2 and additional chart families; check capabilities and chart_catalog first, try live_chart_add, and read back ChartType. xlSuggestedChart is a recommendation sentinel and cannot be saved as a chart type. Extended aliases are subject to host support. Do not represent a failed, changed or unavailable type as success. Existing ChartEx parts may be inspected; use live PowerPoint for advanced changes outside the supported validator generation.",
}
GUIDES["composition"]+=" Bind an Excel range with dataRef={file:'book.xlsx',sheet:'Deposits',headerRow:2,lastRow:6,category:'Quarter',series:[{column:'Retail'}]}. Rows are one-based. Include the sha256 from workspace_read when generating from a particular source revision. Recalculate and save spreadsheet formulas that lack cached values."
