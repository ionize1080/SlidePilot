"""Create an editable wide presentation in a single pass and commit only a complete OPC package."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import os
import re
import tempfile
import unicodedata
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import charts
from package_xml import NS, OFFICE, q, parse, rels, tag, xml, pack
from workspace import confined, resolve_chart, DRAFTS

ASSETS=Path(__file__).resolve().parents[1]/"assets"
PPT="application/vnd.openxmlformats-officedocument.presentationml."
CHART="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
XLSX="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EMU=12700


def bound_text(value,limit,name):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise ValueError(name+" must contain 1.."+str(limit)+" characters")
    return value


def width_units(s):
    return sum(1 if unicodedata.east_asian_width(c) in ("W","F") else .53 for c in s)


def para(body,text,size,tone,bold=False):
    p=tag("a:p",body)
    run=tag("a:r",p)
    pr=tag("a:rPr",run,lang="en-US",sz=round(size*100),b=int(bold))
    charts.solid(pr,tone)
    tag("a:latin",pr,typeface="Calibri")
    tag("a:ea",pr,typeface="Microsoft YaHei")
    tag("a:t",run,text=text)
    return p


def tx(tree,idx,name,x,y,w,h,lines,size,tone,bold=False):
    sp=tag("p:sp",tree)
    nv=tag("p:nvSpPr",sp)
    tag("p:cNvPr",nv,id=idx,name=name)
    tag("p:cNvSpPr",nv,txBox=1)
    tag("p:nvPr",nv)
    prop=tag("p:spPr",sp)
    geom(prop,x,y,w,h)
    tag("a:avLst",tag("a:prstGeom",prop,prst="rect"))
    tag("a:noFill",prop)
    body=tag("p:txBody",sp)
    tag("a:bodyPr",body,wrap="square",lIns=0,rIns=0,tIns=0,bIns=0,anchor="t")
    tag("a:lstStyle",body)
    for line in lines: para(body,line,size,tone,bold)
    return sp


def geom(parent,x,y,w,h,frame=False):
    t=tag("p:xfrm" if frame else "a:xfrm",parent)
    tag("a:off",t,x=round(x*EMU),y=round(y*EMU))
    tag("a:ext",t,cx=round(w*EMU),cy=round(h*EMU))


def frame(tree,idx,name,desc,rect,uri):
    fr=tag("p:graphicFrame",tree)
    nv=tag("p:nvGraphicFramePr",fr)
    tag("p:cNvPr",nv,id=idx,name=name,descr=desc)
    tag("p:cNvGraphicFramePr",nv)
    tag("p:nvPr",nv)
    geom(fr,*rect,frame=True)
    return tag("a:graphicData",tag("a:graphic",fr),uri=uri)


def table(parent,rows,w,h):
    if not 1<=len(rows)<=12 or not 1<=len(rows[0])<=9 or any(len(r)!=len(rows[0]) for r in rows):
        raise ValueError("Native tables require 1..12 uniform rows and 1..9 columns")
    tbl=tag("a:tbl",parent)
    tag("a:tblPr",tbl,firstRow=1,bandRow=1)
    grid=tag("a:tblGrid",tbl)
    for _ in rows[0]: tag("a:gridCol",grid,w=round(w*EMU/len(rows[0])))
    for i,row in enumerate(rows):
        tr=tag("a:tr",tbl,h=round(h*EMU/len(rows)))
        for v in row:
            tc=tag("a:tc",tr)
            body=tag("a:txBody",tc)
            tag("a:bodyPr",body)
            tag("a:lstStyle",body)
            para(body,str(v),min(17,round(h/len(rows)/1.4)),"FFFFFF" if i==0 else "18383D",i==0)
            charts.solid(tag("a:tcPr",tc),"19636C" if i==0 else "F0F5F5" if i%2 else "FFFFFF")


def image_shape(tree,idx,source,rect):
    pic=tag("p:pic",tree)
    nv=tag("p:nvPicPr",pic)
    tag("p:cNvPr",nv,id=idx,name="Image",descr=source.get("alt",""))
    tag("a:picLocks",tag("p:cNvPicPr",nv),noChangeAspect=1)
    tag("p:nvPr",nv)
    fill=tag("p:blipFill",pic)
    tag("a:blip",fill,**{"r:embed":"rIdImage"})
    tag("a:fillRect",tag("a:stretch",fill))
    sp=tag("p:spPr",pic)
    geom(sp,*rect)
    tag("a:avLst",tag("a:prstGeom",sp,prst="rect"))


def notes(text):
    root=parse((ASSETS/"notes.xml").read_bytes())
    tree=root.find("p:cSld/p:spTree",NS)
    sp=tag("p:sp",tree)
    nv=tag("p:nvSpPr",sp)
    tag("p:cNvPr",nv,id=2,name="Speaker notes")
    tag("p:cNvSpPr",nv)
    tag("p:ph",tag("p:nvPr",nv),type="body",idx=1)
    tag("p:spPr",sp)
    b=tag("p:txBody",sp)
    tag("a:bodyPr",b)
    tag("a:lstStyle",b)
    for line in text.splitlines() or [""]: para(b,line,12,"24383B")
    return xml(root)


def compose(root,reader,plan):
    slides=plan["slides"]
    if not isinstance(slides,list) or not 1<=len(slides)<=150: raise ValueError("A deck must contain 1..150 slides")
    with ZipFile(ASSETS/"base.pptx") as z: parts={n:z.read(n) for n in z.namelist()}
    base=parse(parts["ppt/slideLayouts/slideLayout7.xml"]).find("p:cSld/p:spTree",NS)
    for inherited in list(base):
        if inherited.tag not in (q("p:nvGrpSpPr"),q("p:grpSpPr")):
            base.remove(inherited)
    types=parse(parts["[Content_Types].xml"])
    def override(n,t): tag("ct:Override",types,PartName="/"+n,ContentType=t)
    pres=parse(parts["ppt/presentation.xml"])
    size=pres.find("p:sldSz",NS)
    size.attrib={"cx":str(960*EMU),"cy":str(540*EMU)}
    ids=tag("p:sldIdLst")
    pres.insert(1,ids)
    nm=tag("p:notesMasterIdLst")
    tag("p:notesMasterId",nm,**{"r:id":"rIdNotesMaster"})
    pres.insert(1,nm)
    presrels=parse(parts["ppt/_rels/presentation.xml.rels"])
    def presrel(rid,typ,path): tag("rel:Relationship",presrels,Id=rid,Type=OFFICE+"/"+typ,Target=path)
    presrel("rIdNotesMaster","notesMaster","notesMasters/notesMaster1.xml")
    parts["ppt/notesMasters/notesMaster1.xml"]=(ASSETS/"notesMaster.xml").read_bytes()
    # Desktop PowerPoint expects the notes master to own its own theme part.
    parts["ppt/theme/theme2.xml"]=parts["ppt/theme/theme1.xml"]
    override("ppt/theme/theme2.xml","application/vnd.openxmlformats-officedocument.theme+xml")
    parts["ppt/notesMasters/_rels/notesMaster1.xml.rels"]=rels([("rId1","theme","../theme/theme2.xml")])
    override("ppt/notesMasters/notesMaster1.xml",PPT+"notesMaster+xml")
    accent=charts.color(plan.get("accent","19636C"))
    warnings=[]
    chart_no=0
    for i,s in enumerate(slides,1):
        heading=bound_text(s["title"],140,"Slide title")
        body=s.get("body",[])
        if not isinstance(body,list) or len(body)>8: raise ValueError("Use up to eight body paragraphs")
        for txt in body: bound_text(txt,1200,"Paragraph")
        sources=[reader.cite(root,source) for source in s.get("sources",[])]
        content=[key for key in ("chart","table","image") if key in s]
        if len(content)>1: raise ValueError("Use one primary chart, table or image per composed slide")
        is_cover=s.get("layout")=="cover"
        if is_cover and content: raise ValueError("Cover layout expects title and body")
        slide=tag("p:sld",showMasterSp=0)
        cs=tag("p:cSld",slide)
        tree=deepcopy(base)
        cs.append(tree)
        bg=tag("p:bg")
        charts.solid(tag("p:bgPr",bg),"F2F7F6" if is_cover else "FFFFFF")
        cs.insert(0,bg)
        hd_size=44 if is_cover else 32
        title_lines=max(1,int((width_units(heading)*hd_size-1)//866)+1)
        if title_lines>3: raise ValueError("Shorten slide title "+str(i))
        top=112 if is_cover else 32
        hh=title_lines*hd_size*1.25
        tx(tree,2,"Title",48,top,864,hh,[heading],hd_size,accent,True)
        start_y=top+hh+16
        split=bool(content and body)
        bw=280 if split else 864
        bsize=19 if split else 23
        if body:
            lines=sum(max(1,int((width_units(t)*bsize-1)//bw)+1) for t in body)
            if lines*bsize*1.32>496-start_y:
                raise ValueError("Body text would overflow on slide "+str(i)+"; split or shorten the slide")
            tx(tree,3,"Commentary",48,start_y,bw,490-start_y,body,bsize,"263E43")
        x=358 if split else 48
        rect=(x,start_y,912-x,493-start_y)
        links=[("rIdLayout","slideLayout","../slideLayouts/slideLayout7.xml"),("rIdNotes","notesSlide","../notesSlides/notesSlide%d.xml"%i)]
        if "chart" in s:
            chart_no+=1
            spec=resolve_chart(root,s["chart"],reader)
            data,book=charts.build(spec)
            path="ppt/charts/chart%d.xml"%chart_no
            parts[path]=data
            parts["ppt/charts/_rels/chart%d.xml.rels"%chart_no]=rels([("rIdBook","package","../embeddings/Data%d.xlsx"%chart_no)])
            parts["ppt/embeddings/Data%d.xlsx"%chart_no]=book
            override(path,CHART)
            if not any(e.get("Extension")=="xlsx" for e in types): tag("ct:Default",types,Extension="xlsx",ContentType=XLSX)
            tag("c:chart",frame(tree,4,"Chart",spec.get("alt",spec.get("title",heading)),rect,NS["c"]),**{"r:id":"rIdChart"})
            links.append(("rIdChart","chart","../charts/chart%d.xml"%chart_no))
            if "dataRef" in s["chart"]:
                sources.append(s["chart"]["dataRef"]["file"]+" · "+str(len(spec["categories"]))+" data rows")
        if "table" in s:
            table(frame(tree,4,"Table",heading,rect,"http://schemas.openxmlformats.org/drawingml/2006/table"),s["table"],rect[2],rect[3])
        if "image" in s:
            from PIL import Image
            src=s["image"]
            p=confined(root,src["file"])
            if p.stat().st_size>32*1024*1024: raise ValueError("Image exceeds 32 MiB")
            data=p.read_bytes()
            with Image.open(BytesIO(data)) as img:
                if img.format not in ("JPEG","PNG"): raise ValueError("Use JPEG or PNG source images")
                ext="jpeg" if img.format=="JPEG" else "png"
                w,h=img.size
            scale=min(rect[2]/w,rect[3]/h)
            w,h=w*scale,h*scale
            image_shape(tree,4,src,(x+(rect[2]-w)/2,start_y+(rect[3]-h)/2,w,h))
            media="image%d.%s"%(i,ext)
            parts["ppt/media/"+media]=data
            if not any(e.get("Extension")==ext for e in types): tag("ct:Default",types,Extension=ext,ContentType="image/"+ext)
            links.append(("rIdImage","image","../media/"+media))
        if not sources: warnings.append({"slide":i,"warning":"No source locator supplied"})
        tag("a:masterClrMapping",tag("p:clrMapOvr",slide))
        parts["ppt/slides/slide%d.xml"%i]=xml(slide)
        parts["ppt/slides/_rels/slide%d.xml.rels"%i]=rels(links)
        parts["ppt/notesSlides/notesSlide%d.xml"%i]=notes("\n".join([s.get("notes",""),*sources]).strip())
        parts["ppt/notesSlides/_rels/notesSlide%d.xml.rels"%i]=rels([("rIdMaster","notesMaster","../notesMasters/notesMaster1.xml"),("rIdSlide","slide","../slides/slide%d.xml"%i)])
        presrel("s%d"%i,"slide","slides/slide%d.xml"%i)
        tag("p:sldId",ids,id=255+i,**{"r:id":"s%d"%i})
        override("ppt/slides/slide%d.xml"%i,PPT+"slide+xml")
        override("ppt/notesSlides/notesSlide%d.xml"%i,PPT+"notesSlide+xml")
    parts["[Content_Types].xml"]=xml(types)
    parts["ppt/presentation.xml"]=xml(pres)
    parts["ppt/_rels/presentation.xml.rels"]=xml(presrels)
    cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    dc="http://purl.org/dc/elements/1.1/"
    core=ET.Element("{"+cp+"}coreProperties")
    for k,val in (("title",plan.get("title",slides[0]["title"])),("creator","SlidePilot")): ET.SubElement(core,"{"+dc+"}"+k).text=val
    parts["docProps/core.xml"]=xml(core)
    return pack(parts),{"slides":len(slides),"charts":chart_no,"warnings":warnings}


def output_path(root,name):
    if not isinstance(name,str) or not re.fullmatch(r"[^/\\:*?\"<>|\x00-\x1f]{1,100}\.pptx",name,re.I) or Path(name).is_reserved():
        raise ValueError("Choose one .pptx filename without a directory")
    folder=confined(root,DRAFTS+"/drafts",False)
    folder.mkdir(parents=True,exist_ok=True)
    return confined(root,DRAFTS+"/drafts/"+name,False)


def publish_new(dest,data):
    with tempfile.NamedTemporaryFile(dir=dest.parent,prefix=".slidepilot-",suffix=".tmp",delete=False) as f:
        temp=Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        if os.name=="nt": os.rename(temp,dest)  # Windows rename refuses an existing destination.
        else: os.link(temp,dest)
    finally:
        temp.unlink(missing_ok=True)
