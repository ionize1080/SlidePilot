from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"engine"))
from chart_types import TYPES
from workspace import Reader
from decks import compose

def small_plan():
    return {"title":"Harbour deposit review","slides":[
        {"layout":"cover","title":"Harbour deposit review","body":["Quarterly briefing · SGD millions"],
         "sources":[{"file":"brief.md","locator":"line 2","quote":"SGD 142 million"}]},
        {"title":"Retail deposits rose from SGD 100m to SGD 142m","body":["Business deposits rose from SGD 82m to SGD 94m."],
         "chart":{"type":"xlColumnClustered","numberFormat":"0","yAxis":{"title":"SGD millions","min":0},
                  "dataRef":{"file":"deposits.csv","category":"Quarter","series":[{"column":"Retail deposits (SGD m)","name":"Retail"},{"column":"Business deposits (SGD m)","name":"Business"}]}},
         "sources":[{"file":"deposits.csv","locator":"row 5","quote":"Q4 | 142 | 94"}]},
        {"title":"The January review will assess the pricing pilot","body":["The pilot started in Q3.","The observed deposit increase does not establish a causal link."],
         "sources":[{"file":"brief.md","locator":"line 4","quote":"review the pilot in January"}]}]}

def chart_fixture(name):
    family=TYPES[name][1]
    spec={"type":name,"categories":["A","B","C"],"title":name}
    n={"stock":{"xlStockHLC":3,"xlStockOHLC":4,"xlStockVHLC":4,"xlStockVOHLC":5}.get(name,0),
       "pie":1,"surface":3,"combo":2}.get(family,2)
    stock={"xlStockHLC":["High","Low","Close"],"xlStockOHLC":["Open","High","Low","Close"],
           "xlStockVHLC":["Volume","High","Low","Close"],"xlStockVOHLC":["Volume","Open","High","Low","Close"]}
    stock_vals={"Volume":[110,142,166],"Open":[11,12,14],"High":[14,16,17],"Low":[9,10,12],"Close":[12,13,15]}
    spec["series"]=[]
    for i in range(n):
        s={"name":"Series "+str(i+1),"values":[2+i,6+i,4+i]}
        if family=="stock":
            s["name"]=stock[name][i]
            s["values"]=stock_vals[s["name"]]
        if family in ("scatter","bubble"): s["x"]=[1,2,4]
        if family=="bubble": s["sizes"]=[1,6,2]
        spec["series"].append(s)
    return spec

if __name__=="__main__":
    out=ROOT/".build/qa"
    out.mkdir(parents=True,exist_ok=True)
    root=ROOT/"examples/workspace"
    (out/"Harbour.pptx").write_bytes(compose(root,Reader(),small_plan())[0])
    names=[n for n,(_,g) in TYPES.items() if g not in ("modern","recommended")]
    (out/"ChartMatrix.pptx").write_bytes(compose(root,Reader(),{"slides":[{"title":n,"chart":chart_fixture(n)} for n in names]})[0])
    print("Embedded chart variants",len(names),"catalogued",len(TYPES))
