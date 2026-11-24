"""Small OPC helpers shared by the presentation writer and the independent workspace reader."""
import io
import math
import posixpath
import re
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = dict(p="http://schemas.openxmlformats.org/presentationml/2006/main",
          a="http://schemas.openxmlformats.org/drawingml/2006/main",
          c="http://schemas.openxmlformats.org/drawingml/2006/chart",
          cx="http://schemas.microsoft.com/office/drawing/2014/chartex",
          s="http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          w="http://schemas.openxmlformats.org/wordprocessingml/2006/main", r=OFFICE,
          rel="http://schemas.openxmlformats.org/package/2006/relationships",
          ct="http://schemas.openxmlformats.org/package/2006/content-types")
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def q(name):
    prefix, local = name.split(":")
    return "{%s}%s" % (NS[prefix], local)


def tag(tag_name, parent=None, text=None, **attrs):
    el = ET.Element(q(tag_name)) if parent is None else ET.SubElement(parent, q(tag_name))
    for key, value in attrs.items():
        el.set(q(key) if ":" in key else key, str(value))
    if text is not None:
        val = str(text)
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", val):
            raise ValueError("Text contains an invalid XML control character")
        el.text = val
    return el


def xml(el):
    data = ET.tostring(el, encoding="utf-8", xml_declaration=True)
    # WindowsBase's Office 2010 OPC reader expects unprefixed package markup.
    for prefix in ("ct", "rel"):
        if el.tag.startswith("{"+NS[prefix]+"}"):
            p=prefix.encode()
            return data.replace(b"<"+p+b":",b"<").replace(b"</"+p+b":",b"</").replace(b"xmlns:"+p+b"=",b"xmlns=")
    return data


def parse(data):
    if len(data) > 32 * 1024 * 1024 or b"<!DOCTYPE" in data.upper():
        raise ValueError("Unsafe or oversized XML part")
    return ET.fromstring(data)


def rels(entries):
    el = tag("rel:Relationships")
    for rid, typ, target in entries:
        tag("rel:Relationship", el, Id=rid, Type=typ if "://" in typ else OFFICE + "/" + typ, Target=target)
    return xml(el)


def relationships(z, part):
    folder, name = posixpath.split(part)
    rp = posixpath.join(folder, "_rels", name + ".rels")
    if rp not in z.namelist():
        return {}
    return {n.get("Id"):posixpath.normpath(posixpath.join(folder, n.get("Target").lstrip("/"))) if not n.get("Target").startswith("/") else n.get("Target")[1:]
            for n in parse(z.read(rp)) if n.get("TargetMode") != "External"}


def pack(parts):
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=3) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return output.getvalue()


def column(index):
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def numeric(v):
    return type(v) in (int, float) and math.isfinite(v)


def workbook(rows, formats=None):
    ss = "application/vnd.openxmlformats-officedocument.spreadsheetml."
    types = tag("ct:Types")
    tag("ct:Default", types, Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
    for name, typ in (("workbook","sheet.main"),("worksheets/sheet1","worksheet"),("styles","styles")):
        tag("ct:Override", types, PartName="/xl/" + name + ".xml", ContentType=ss + typ + "+xml")
    book = tag("s:workbook")
    tag("s:sheet", tag("s:sheets", book), name="Data", sheetId=1, **{"r:id":"rId1"})
    sheet = tag("s:worksheet")
    data = tag("s:sheetData",sheet)
    styles = tag("s:styleSheet")
    formats = list(dict.fromkeys(formats or []))
    if formats:
        fmts = tag("s:numFmts",styles,count=len(formats))
        for i, fmt in enumerate(formats):
            tag("s:numFmt",fmts,numFmtId=164+i,formatCode=fmt)
    tag("s:font",tag("s:fonts",styles,count=1))
    fills = tag("s:fills",styles,count=2)
    for pattern in ("none","gray125"):
        tag("s:patternFill",tag("s:fill",fills),patternType=pattern)
    tag("s:border",tag("s:borders",styles,count=1))
    xfs = tag("s:cellXfs",styles,count=1+len(formats))
    for fmt_id in [0] + list(range(164,164+len(formats))):
        tag("s:xf",xfs,numFmtId=fmt_id,fontId=0,fillId=0,borderId=0)
    for ri, row in enumerate(rows, 1):
        r = tag("s:row",data,r=ri)
        for ci, value in enumerate(row,1):
            if value is None:
                continue
            cell = tag("s:c",r,r=column(ci)+str(ri))
            if numeric(value):
                tag("s:v",cell,text=value)
                if formats and ci > 1 and ri > 1:
                    cell.set("s","1")
            else:
                cell.set("t","inlineStr")
                tag("s:t",tag("s:is",cell),text=value)
    return pack({"[Content_Types].xml":xml(types),"_rels/.rels":rels([("rId1","officeDocument","xl/workbook.xml")]),
                 "xl/workbook.xml":xml(book),"xl/styles.xml":xml(styles),"xl/worksheets/sheet1.xml":xml(sheet),
                 "xl/_rels/workbook.xml.rels":rels([("rId1","worksheet","worksheets/sheet1.xml"),("rId2","styles","styles.xml")])})
