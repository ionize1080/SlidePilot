"""Read only the workspace chosen by the person in PowerPoint. Locators survive pagination."""
import csv
import hashlib
import io
import os
from pathlib import Path
import re
from zipfile import ZipFile
from package_xml import NS, parse, q, relationships

FORMATS={".txt",".md",".csv",".tsv",".docx",".pptx",".xlsx",".pdf"}
DRAFTS="_SlidePilot"


def confined(root, relative, exists=True):
    root=Path(root).resolve(strict=True)
    part=Path(relative)
    if not relative or part.is_absolute() or part.drive or ".." in part.parts or any(":" in c for c in part.parts):
        raise ValueError("Use a workspace-relative file name")
    dest=(root/part).resolve(strict=exists)
    if dest==root or not dest.is_relative_to(root): raise ValueError("Path leaves the chosen workspace")
    return dest


def files(root):
    root=Path(root).resolve(strict=True)
    for folder,dirs,names in os.walk(root):
        dirs[:]=sorted(d for d in dirs if not d.startswith(".") and d!=DRAFTS and not (Path(folder)/d).is_symlink()
                       and not os.path.isjunction(Path(folder)/d))
        for name in sorted(names):
            p=Path(folder)/name
            if p.suffix.lower() in FORMATS and not name.startswith(("~$",".")) and not p.is_symlink():
                yield {"file":p.relative_to(root).as_posix(),"bytes":p.stat().st_size}


def decode(raw):
    if raw.startswith((b"\xff\xfe",b"\xfe\xff")): return raw.decode("utf-16")
    for enc in ("utf-8-sig","gb18030"):
        try: return raw.decode(enc)
        except UnicodeDecodeError: pass
    raise ValueError("Text encoding must be UTF-8, UTF-16 or GB18030")


def checked_zip(data):
    z=ZipFile(io.BytesIO(data))
    entries=z.infolist()
    if len(entries)>12000 or sum(f.file_size for f in entries)>256*1024*1024 or any(f.file_size>64*1024*1024 for f in entries):
        z.close()
        raise ValueError("Workspace document exceeds extraction limits")
    return z


def records(path):
    if path.stat().st_size>64*1024*1024: raise ValueError("Source exceeds 64 MiB")
    raw=path.read_bytes()
    suffix=path.suffix.lower()
    if suffix not in FORMATS: raise ValueError("Unsupported source format")
    if suffix in (".md",".txt"):
        return [("line "+str(i),v) for i,v in enumerate(decode(raw).splitlines(),1) if v.strip()]
    if suffix in (".csv",".tsv"):
        rows=csv.reader(io.StringIO(decode(raw)),delimiter="\t" if suffix==".tsv" else ",")
        return [("row "+str(i)," | ".join(row)) for i,row in enumerate(rows,1)]
    if suffix==".pdf":
        import pypdfium2 as pdf
        result=[]
        with pdf.PdfDocument(raw) as doc:
            for i in range(len(doc)):
                page=doc[i]
                try:
                    text=page.get_textpage()
                    try: result.append(("page "+str(i+1),text.get_text_bounded().strip()))
                    finally: text.close()
                finally: page.close()
        return result
    with checked_zip(raw) as z:
        if suffix==".docx":
            root=parse(z.read("word/document.xml"))
            return [("paragraph "+str(i),"".join(n.text or "" for n in p.iter(q("w:t"))))
                    for i,p in enumerate(root.iter(q("w:p")),1)]
        if suffix==".pptx":
            p="ppt/presentation.xml"
            rel=relationships(z,p)
            return [("slide "+str(i),"\n".join("".join(t.text or "" for t in p.iter(q("a:t"))) for p in parse(z.read(rel[s.get(q("r:id"))])).iter(q("a:p"))))
                    for i,s in enumerate(parse(z.read(p)).findall("p:sldIdLst/p:sldId",NS),1)]
        root=parse(z.read("xl/workbook.xml"))
        rel=relationships(z,"xl/workbook.xml")
        strings=[]
        if "xl/sharedStrings.xml" in z.namelist():
            strings=["".join(t.text or "" for t in s.iter(q("s:t"))) for s in parse(z.read("xl/sharedStrings.xml"))]
        out=[]
        for sheet in root.findall("s:sheets/s:sheet",NS):
            data=parse(z.read(rel[sheet.get(q("r:id"))]))
            for row in data.findall(".//s:row",NS):
                vals=[]
                for c in row.findall("s:c",NS):
                    val=c.findtext("s:v","",NS)
                    if c.get("t")=="inlineStr": val="".join(t.text or "" for t in c.iter(q("s:t")))
                    elif c.get("t")=="s": val=strings[int(val)]
                    elif not val and c.find("s:f",NS) is not None: val="="+c.findtext("s:f","",NS)+" [uncalculated]"
                    vals.append(c.get("r","")+"="+val)
                out.append((sheet.get("name")+"!"+row.get("r","?")," | ".join(vals)))
        return out


class Reader:
    def __init__(self):
        self.cache={}

    def snapshot(self,root,file):
        p=confined(root,file)
        if p.stat().st_size>64*1024*1024: raise ValueError("Source exceeds 64 MiB")
        sig=(p.stat().st_mtime_ns,p.stat().st_size)
        cached=self.cache.get(p)
        if not cached or cached[0]!=sig:
            rows=records(p)
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            if (p.stat().st_mtime_ns,p.stat().st_size)!=sig: raise ValueError("Source changed while reading; retry")
            if len(self.cache)>=8: self.cache.pop(next(iter(self.cache)))
            self.cache[p]=(sig,rows,digest)
        return self.cache[p][1:]

    def read(self,root,file,start=0,limit=60,query=""):
        rows,digest=self.snapshot(root,file)
        hits=[(k,v) for k,v in rows if query.casefold() in v.casefold()]
        if start<0 or not 1<=limit<=150: raise ValueError("Use start >= 0 and limit 1..150")
        chunk=[]
        for k,v in hits[start:start+limit]:
            if chunk and sum(len(e["text"]) for e in chunk)+len(v)>24000: break
            chunk.append({"locator":k,"text":v[:24000],"text_truncated":len(v)>24000})
        end=start+len(chunk)
        return {"file":file,"sha256":digest,"total":len(hits),"next":end if end<len(hits) else None,"records":chunk}

    def cite(self,root,source):
        rows,digest=self.snapshot(root,source["file"])
        if source.get("sha256",digest)!=digest: raise ValueError("Source changed: "+source["file"])
        quote=source["quote"].strip()
        if not quote or not any(k==source["locator"] and quote in v for k,v in rows):
            raise ValueError("Source quote does not match its locator: "+source["file"]+" "+source["locator"])
        return "%s · %s · %s"%(source["file"],source["locator"],quote)


def spreadsheet_rows(raw, selected):
    with checked_zip(raw) as z:
        workbook=parse(z.read("xl/workbook.xml"))
        sheets=workbook.findall("s:sheets/s:sheet",NS)
        names=[s.get("name") for s in sheets]
        if selected is None and len(names)==1:
            selected=names[0]
        if selected not in names:
            raise ValueError("Choose a worksheet by name: "+", ".join(names))
        part=relationships(z,"xl/workbook.xml")[sheets[names.index(selected)].get(q("r:id"))]
        shared=[]
        if "xl/sharedStrings.xml" in z.namelist():
            shared=["".join(t.text or "" for t in item.iter(q("s:t"))) for item in parse(z.read("xl/sharedStrings.xml"))]
        for row in parse(z.read(part)).findall("s:sheetData/s:row",NS):
            fields={}
            for cell in row.findall("s:c",NS):
                col=re.match(r"[A-Z]+",cell.get("r",""))
                if not col:
                    raise ValueError("Missing worksheet cell address")
                value=cell.findtext("s:v",None,NS)
                kind=cell.get("t")
                if kind=="s":
                    value=shared[int(value)]
                elif kind=="inlineStr":
                    value="".join(t.text or "" for t in cell.iter(q("s:t")))
                elif value is None and cell.find("s:f",NS) is not None:
                    value="=uncalculated"
                fields[col[0]]=value
            yield int(row.get("r")),fields


def resolve_chart(root,spec,reader=None):
    ref=spec.get("dataRef")
    if not ref: return spec
    p=confined(root,ref["file"])
    if p.suffix.lower() not in (".csv",".tsv",".xlsx") or p.stat().st_size>8*1024*1024:
        raise ValueError("dataRef requires a CSV, TSV or XLSX up to 8 MiB")
    raw=p.read_bytes()
    cached=reader.cache.get(p) if reader else None
    digest=hashlib.sha256(raw).hexdigest()
    if ref.get("sha256",digest)!=digest or cached and cached[2]!=digest:
        raise ValueError("Chart source changed; read it again: "+ref["file"])
    first=ref.get("headerRow",1)
    last=ref.get("lastRow")
    if first<1 or last is not None and last<=first:
        raise ValueError("Use a positive headerRow and a lastRow below the headers")
    if p.suffix.lower()==".xlsx":
        stream=spreadsheet_rows(raw,ref.get("sheet"))
    else:
        if "sheet" in ref:
            raise ValueError("sheet applies to XLSX only")
        table=csv.reader(io.StringIO(decode(raw)),delimiter="\t" if p.suffix.lower()==".tsv" else ",")
        stream=((i,dict(enumerate(row))) for i,row in enumerate(table,1))
    needed={ref["category"]}
    for s in ref["series"]:
        needed.update(s[k] for k in ("column","xColumn","sizeColumn") if k in s)
    headers={}
    rows=[]
    for i,fields in stream:
        if i<first:continue
        if last is not None and i>last:break
        if i==first:
            for key,label in fields.items():
                if label in needed:
                    if label in headers:raise ValueError("Ambiguous chart column: "+label)
                    headers[label]=key
            if needed-headers.keys():raise ValueError("Missing chart columns: "+", ".join(sorted(needed-headers.keys())))
        elif any(fields.get(k) not in (None,"") for k in headers.values()):
            rows.append({name:fields.get(k) for name,k in headers.items()})
            if len(rows)>10000:raise ValueError("Select up to 10000 data rows")
    if not 1<=len(rows)<=10000: raise ValueError("Source must have 1..10000 data rows")
    def number(raw):
        return float(raw.strip()) if raw is not None and raw.strip() else None
    result={**spec,"categories":[r[ref["category"]] or "" for r in rows],"series":[]}
    for s in ref["series"]:
        entry={k:v for k,v in s.items() if k not in ("column","xColumn","sizeColumn")}
        entry.update(name=s.get("name",s["column"]),values=[number(r[s["column"]]) for r in rows])
        for prop,col in (("x","xColumn"),("sizes","sizeColumn")):
            if col in s: entry[prop]=[number(r[s[col]]) for r in rows]
        result["series"].append(entry)
    return result
