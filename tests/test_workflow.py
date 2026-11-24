import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from fixtures import ROOT, chart_fixture, small_plan
from chart_edit import FORMULA, inspect, part_for, patch
from chart_types import TYPES, catalogue
from decks import compose, publish_new
from package_xml import NS, parse, q, relationships, workbook
from server import Service, response
from workspace import Reader, resolve_chart


def workbook_cells(data):
    with ZipFile(BytesIO(data)) as book:
        sheet=parse(book.read("xl/worksheets/sheet1.xml"))
        return {cell.get("r"):cell.findtext("s:v",namespaces=NS) if cell.get("t")!="inlineStr"
                else "".join(t.text or "" for t in cell.iter(q("s:t"))) for cell in sheet.iter(q("s:c"))}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name)
        shutil.copytree(ROOT/"examples/workspace",self.work,dirs_exist_ok=True)
        self.reader=Reader()

    def draft(self,name,plan):
        data,_=compose(self.work,self.reader,plan)
        path=self.work/name
        path.write_bytes(data)
        return path

    def test_all_classic_charts_match_their_embedded_cells(self):
        classic=[n for n,(_,g) in TYPES.items() if g not in ("modern","recommended")]
        path=self.draft("Matrix.pptx",{"slides":[{"title":n,"chart":chart_fixture(n)} for n in classic]})
        with ZipFile(path) as z:
            charts=part_for(z,None)
            self.assertEqual(len(charts),78)
            seen=set()
            for name,(_slide,part) in zip(classic,charts):
                with self.subTest(name=name):
                    drawing=parse(z.read(part))
                    rid=drawing.find("c:externalData",NS).get(q("r:id"))
                    bookname=relationships(z,part)[rid]
                    self.assertNotIn(bookname,seen)
                    seen.add(bookname)
                    cells=workbook_cells(z.read(bookname))
                    for tag in ("strRef","numRef"):
                        for ref in drawing.iter(q("c:"+tag)):
                            formula=FORMULA.fullmatch(ref.findtext("c:f",namespaces=NS))
                            col,first,last_col,last=formula.groups()
                            self.assertIn(last_col,(None,col))
                            cache=ref.find("c:"+tag.replace("Ref","Cache"),NS)
                            points={int(e.get("idx")):e.findtext("c:v",namespaces=NS) for e in cache.findall("c:pt",NS)}
                            length=int(last or first)-int(first)+1
                            self.assertEqual(int(cache.find("c:ptCount",NS).get("val")),length)
                            for i in range(length):
                                self.assertEqual(points.get(i),cells.get(col+str(int(first)+i)))

    def test_notes_have_an_independent_theme_and_verified_quotes(self):
        path=self.draft("Brief.pptx",small_plan())
        with ZipFile(path) as z:
            slide_theme=relationships(z,"ppt/slideMasters/slideMaster1.xml")
            notes_theme=relationships(z,"ppt/notesMasters/notesMaster1.xml")["rId1"]
            self.assertNotIn(notes_theme,slide_theme.values())
            self.assertIn(notes_theme,z.namelist())
            self.assertIn("Q4 | 142 | 94",z.read("ppt/notesSlides/notesSlide2.xml").decode())
        plan=small_plan()
        plan["slides"][1]["sources"][0]["quote"]="Q4 | 200 | 94"
        with self.assertRaisesRegex(ValueError,"quote"):
            compose(self.work,self.reader,plan)

    def test_surgical_edits_sync_cache_and_file_without_replacing_original(self):
        source=self.draft("Brief.pptx",small_plan())
        original=hashlib.sha256(source.read_bytes()).digest()
        path=inspect(source,1,contains="gapWidth")["nodes"][0]["path"]
        result=patch(source,1,[{"path":path,"attributes":{"val":85}}],
                     [{"cell":"B5","value":155},{"cell":"C3","value":None},{"cell":"B1","value":"Retail revised"}])
        self.assertEqual(original,hashlib.sha256(source.read_bytes()).digest())
        with ZipFile(BytesIO(result)) as z:
            part=part_for(z,1)
            cells=workbook_cells(z.read(next(iter(relationships(z,part).values()))))
            self.assertEqual((cells["B5"],cells["B1"],cells.get("C3")),("155","Retail revised",None))
            drawing=parse(z.read(part))
            self.assertEqual(drawing.find(".//c:gapWidth",NS).get("val"),"85")
            series=drawing.findall(".//c:ser",NS)
            self.assertEqual(series[0].findtext("c:val/c:numRef/c:numCache/c:pt[@idx='3']/c:v",namespaces=NS),"155")
            self.assertIsNone(series[1].find("c:val/c:numRef/c:numCache/c:pt[@idx='1']",NS))

    def test_selected_worksheet_and_row_range(self):
        source=self.work/"actuals.xlsx"
        source.write_bytes(workbook([["Quarterly review"],["Quarter",None,"Retail","Business"],
                                     ["Q1",None,100,82],["Q2",None,None,85],["Total",None,100,167]]))
        spec={"type":"xlLine","dataRef":{"file":source.name,"sheet":"Data","headerRow":2,"lastRow":4,
                 "category":"Quarter","series":[{"column":"Retail"},{"column":"Business"}]}}
        result=resolve_chart(self.work,spec)
        self.assertEqual(result["categories"],["Q1","Q2"])
        self.assertEqual([s["values"] for s in result["series"]],[[100,None],[82,85]])
        spec["dataRef"]["sheet"]="Other"
        with self.assertRaisesRegex(ValueError,"worksheet"):
            resolve_chart(self.work,spec)

    def test_source_digest_changes_before_composition(self):
        plan=small_plan()
        spec=plan["slides"][1]["chart"]
        source=self.work/"deposits.csv"
        read=self.reader.read(self.work,source.name)
        spec["dataRef"]["sha256"]=read["sha256"]
        source.write_bytes(source.read_bytes().replace(b"142",b"150"))
        with self.assertRaisesRegex(ValueError,"changed"):
            resolve_chart(self.work,spec,self.reader)

    def test_source_columns_must_be_unambiguous(self):
        (self.work/"ambiguous.csv").write_text("Quarter,Value,Value\nQ1,2,3")
        spec={"dataRef":{"file":"ambiguous.csv","category":"Quarter","series":[{"column":"Value"}]}}
        with self.assertRaisesRegex(ValueError,"Ambiguous"):
            resolve_chart(self.work,spec)

    def test_binding_and_no_overwrite(self):
        source=self.work/"existing.pptx"
        source.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            publish_new(source,b"replacement")
        self.assertEqual(source.read_bytes(),b"original")
        with self.assertRaises(ValueError):
            self.reader.read(self.work,"../outside.txt")

    def test_guides_match_the_live_member_inventory(self):
        result=Service().call("guide",{"topic":"formatting"})["liveMembers"]
        native=(ROOT/"native/OfficeGraph.cs").read_text(encoding="utf-8")
        for label,entries in re.findall(r'internal const string (Children|Writable|Methods)="([^"]+)";',native):
            self.assertEqual(result[label.lower()],entries.split())
        catalog=catalogue()
        self.assertEqual(sum(e["route"]=="live_probe" for e in catalog),24)
        self.assertEqual(sum(e["route"]=="recommendation_only" for e in catalog),1)

    def test_mcp_stdio_handshake_and_schema_errors(self):
        def request(id,method,**params):
            return {"jsonrpc":"2.0","id":id,"method":method,"params":params}
        frames=[request(1,"initialize",protocolVersion="2025-03-26"),{"jsonrpc":"2.0","method":"notifications/initialized"},
                request(2,"tools/list"),request(3,"tools/call",name="guide",arguments={"topic":"formatting"}),
                request(4,"tools/call",name="guide",arguments={"topic":"unknown"})]
        result=subprocess.run([sys.executable,"-B",str(ROOT/"engine/server.py")],
                              input=b"".join((json.dumps(f)+"\n").encode() for f in frames),capture_output=True,check=True,timeout=15)
        replies=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies],[1,2,3,4])
        self.assertEqual(replies[0]["result"]["protocolVersion"],"2025-03-26")
        self.assertIn("deck_compose",[t["name"] for t in replies[1]["result"]["tools"]])
        self.assertIn("liveMembers",json.loads(replies[2]["result"]["content"][0]["text"]))
        self.assertTrue(replies[3]["result"]["isError"])


if __name__=="__main__":
    unittest.main()
