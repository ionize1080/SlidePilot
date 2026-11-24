"""Inspect OPC relationships, edit style subtrees and synchronize cells with chart caches."""
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile
from package_xml import NS, column, numeric, pack, parse, q, relationships, xml
from workspace import checked_zip

PREFIX={uri:k for k,uri in NS.items()}
CELL=re.compile(r"([A-Z]{1,3})([1-9][0-9]*)$")
FORMULA=re.compile(r"(?:'Data'|Data)!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?$")
SAFE_NS={NS["c"],NS["a"],NS["cx"]}
PROTECTED={"chartSpace","externalData","chartData","strRef","numRef","strCache","numCache","multiLvlStrRef","multiLvlStrCache",
           "ptCount","f","axId","crossAx","dataId","numDim","strDim","ext","extLst","hlinkClick","hlinkMouseOver","blip"}


def part_for(z,index):
    doc="ppt/presentation.xml"
    ids=parse(z.read(doc)).findall("p:sldIdLst/p:sldId",NS)
    deck_rels=relationships(z,doc)
    parts=[]
    for slide_no,entry in enumerate(ids,1):
        slide=deck_rels[entry.get(q("r:id"))]
        rel=relationships(z,slide)
        for g in parse(z.read(slide)).iter(q("a:graphicData")):
            ch=next((n for n in g if n.tag in (q("c:chart"),q("cx:chart"))),None)
            if ch is not None: parts.append((slide_no,rel[ch.get(q("r:id"))]))
    if index is None:return parts
    if not 1<=index<=len(parts):raise ValueError("Chart index is outside the presentation")
    return parts[index-1][1]


def tree(el,path="",protected=False):
    counts={}
    for child in el:
        uri,loc=child.tag[1:].split("}",1)
        if uri not in SAFE_NS:continue
        key=PREFIX[uri]+":"+loc
        counts[key]=counts.get(key,0)+1
        childpath=(path+"/" if path else "")+key+"["+str(counts[key])+"]"
        lock=protected or loc in PROTECTED
        yield {"path":childpath,"attributes":child.attrib,"text":(child.text or "")[:200],"protected":lock}
        yield from tree(child,childpath,lock)


def inspect(source,index=None,start=0,limit=100,contains=""):
    with checked_zip(source.read_bytes()) as z:
        if index is None:
            names=part_for(z,None)
            return {"charts":[{"index":i,"slide":s,"part":p,"relationships":relationships(z,p)} for i,(s,p) in enumerate(names,1)]}
        part=part_for(z,index)
        found=[row for row in tree(parse(z.read(part))) if contains.casefold() in row["path"].casefold()]
        return {"part":part,"total":len(found),"next":start+limit if start+limit<len(found) else None,"nodes":found[start:start+limit]}


def set_cells(parts,part,drawing,book_name,changes):
    with checked_zip(parts[book_name]) as b:
        if "xl/worksheets/sheet1.xml" not in b.namelist(): raise ValueError("Unknown embedded sheet layout")
        sheet=parse(b.read("xl/worksheets/sheet1.xml"))
        wbparts={n:b.read(n) for n in b.namelist()}
        if parse(b.read("xl/workbook.xml")).find("s:sheets/s:sheet",NS).get("name")!="Data": raise ValueError("Cell edits require a SlidePilot Data sheet; use live_chart_data for other workbooks")
    sheetdata=sheet.find("s:sheetData",NS)
    def cindex(col):
        n=0
        for c in col:n=n*26+ord(c)-64
        return n
    cache={}
    for ref in drawing.iter():
        if ref.tag not in (q("c:strRef"),q("c:numRef")):continue
        form=FORMULA.fullmatch(ref.findtext("c:f","",NS))
        if not form:raise ValueError("Unsupported formula. Use live_chart_data for external or complex data ranges")
        c,r,endc,endr=form.groups()
        if endc is not None and endc!=c:raise ValueError("Only column-oriented ranges can be edited offline")
        r,endr=int(r),int(endr or r)
        child=ref.find("c:strCache",NS) if ref.tag==q("c:strRef") else ref.find("c:numCache",NS)
        if child is None or endr-r>10000: raise ValueError("Unexpected chart cache")
        for idx in range(endr-r+1): cache.setdefault(c+str(r+idx),[]).append((child,idx,ref.tag==q("c:numRef")))
    for edit in changes:
        adr=edit["cell"].upper();m=CELL.fullmatch(adr);value=edit["value"]
        if not m or adr not in cache:raise ValueError("Cell is outside the chart formula ranges: "+adr)
        if value is not None and not isinstance(value,str) and not numeric(value):raise ValueError("Invalid cell value")
        if any(is_num for _,_,is_num in cache[adr]) and value is not None and not numeric(value):raise ValueError("Numeric cache requires a number or null")
        row=sheetdata.find("s:row[@r='%s']"%m[2],NS)
        if row is None:raise ValueError("Missing worksheet row")
        cell=row.find("s:c[@r='%s']"%adr,NS)
        if cell is None:
            from xml.etree.ElementTree import Element
            cell=Element(q("s:c"),{"r":adr})
            ix=next((i for i,x in enumerate(row) if cindex(CELL.fullmatch(x.get("r"))[1])>cindex(m[1])),len(row))
            row.insert(ix,cell)
        for ch in list(cell):cell.remove(ch)
        cell.attrib.pop("t",None)
        from package_xml import tag
        if isinstance(value,str):cell.set("t","inlineStr");tag("s:t",tag("s:is",cell),text=value)
        elif value is not None:tag("s:v",cell,text=value)
        for cache_node,idx,_ in cache[adr]:
            pt=cache_node.find("c:pt[@idx='%d']"%idx,NS)
            if value is None:
                if pt is not None:cache_node.remove(pt)
                continue
            if pt is None:
                from xml.etree.ElementTree import Element
                pt=Element(q("c:pt"),{"idx":str(idx)})
                pos=next((i for i,n in enumerate(cache_node) if n.tag==q("c:pt") and int(n.get("idx"))>idx),len(cache_node))
                cache_node.insert(pos,pt)
            v=pt.find("c:v",NS)
            if v is None:v=tag("c:v",pt)
            v.text=str(value)
    wbparts["xl/worksheets/sheet1.xml"]=xml(sheet)
    parts[book_name]=pack(wbparts)


def patch(source,index,edits,cells):
    if not 1<=len(edits)+len(cells)<=500:raise ValueError("Use 1..500 edits per review")
    with checked_zip(source.read_bytes()) as z:
        part=part_for(z,index)
        drawing=parse(z.read(part))
        parts={n:z.read(n) for n in z.namelist()}
        embedded=drawing.find("c:externalData",NS)
        if cells:
            if embedded is None:raise ValueError("Use live_chart_data for ChartEx or linked workbooks")
            book=relationships(z,part).get(embedded.get(q("r:id")))
            if not book or not book.startswith("ppt/embeddings/"):raise ValueError("An embedded workbook is required")
            set_cells(parts,part,drawing,book,cells)
    for edit in edits:
        path=edit["path"]
        if not re.fullmatch(r"(?:c|a|cx):[A-Za-z][A-Za-z0-9]*\[[1-9][0-9]*\](?:/(?:c|a|cx):[A-Za-z][A-Za-z0-9]*\[[1-9][0-9]*\])*",path):
            raise ValueError("Use an exact path returned by chart_inspect")
        if any(p.split(":")[1].split("[")[0] in PROTECTED for p in path.split("/")): raise ValueError("Use cell edits for workbook-backed values; chart relationships are protected.")
        node=drawing.find(path,NS)
        if node is None:raise ValueError("Chart node no longer exists: "+path)
        action=edit.get("op","set")
        if action=="remove":
            parent=drawing.find(path.rsplit("/",1)[0],NS) if "/" in path else drawing
            parent.remove(node);continue
        if action=="insert":
            name=edit["tag"]
            if not re.fullmatch(r"(?:c|a|cx):[A-Za-z][A-Za-z0-9]*",name) or name.split(":")[1] in PROTECTED:raise ValueError("Unsupported child")
            from xml.etree.ElementTree import Element
            new=Element(q(name));node.insert(int(edit.get("index",len(node))),new);node=new
        elif action!="set": raise ValueError("Unknown chart edit")
        for k,v in edit.get("attributes",{}).items():
            if not re.fullmatch("[A-Za-z][A-Za-z0-9]*",k) or k in ("xmlns","id") and node.tag==q("cx:series"):raise ValueError("Unsupported chart attribute")
            if v is None:node.attrib.pop(k,None)
            else:node.set(k,str(v))
        if "text" in edit:node.text=str(edit["text"])
    parts[part]=xml(drawing)
    return pack(parts)
