"""SlidePilot MCP server. UTF-8, newline-framed JSON-RPC over inherited stdio only."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

if __package__ in (None,"") and str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0,str(Path(__file__).resolve().parent))
import chart_edit
from chart_types import TYPES, canonical, catalogue
from catalog import GUIDES, TOOLS
from decks import compose, output_path
from package_xml import NS, parse, q, relationships
from workspace import Reader, checked_zip, confined, files, DRAFTS

ROOT=Path(__file__).resolve().parents[1]
VERSIONS=("2025-11-25","2025-06-18","2025-03-26","2024-11-05")


def native(action,**payload):
    name=os.environ.get("SLIDEPILOT_PIPE","")
    token=os.environ.get("SLIDEPILOT_TOKEN","")
    if not re.fullmatch("SlidePilot-[0-9a-f]{32}",name) or not re.fullmatch("[A-F0-9]{64}",token):
        raise RuntimeError("Open SlidePilot from the PowerPoint ribbon to bind a host")
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    create=kernel.CreateFileW
    create.argtypes=(wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE)
    create.restype=wintypes.HANDLE
    path="\\\\.\\pipe\\"+name
    # The host recreates its pipe instance after every reply. Opening first also
    # avoids a gap between a successful wait and a competing UI heartbeat.
    deadline=time.monotonic()+30
    while True:
        handle=create(path,0xC0000000,0,None,3,0,None)
        if handle!=wintypes.HANDLE(-1).value:
            break
        error=ctypes.get_last_error()
        if error not in (2,231) or time.monotonic()>=deadline:
            raise RuntimeError(f"PowerPoint pipe unavailable (Windows error {error}). Read context again.")
        time.sleep(.04)
    try:
        fd=msvcrt.open_osfhandle(handle,os.O_BINARY|os.O_RDWR)
    except OSError:
        kernel.CloseHandle(wintypes.HANDLE(handle))
        raise
    with os.fdopen(fd,"r+b",buffering=0) as conn:
        conn.write((json.dumps({"action":action,"token":token,**payload},ensure_ascii=False)+"\n").encode())
        with __import__("io").BufferedReader(conn) as reader:
            line=reader.readline(10*1024*1024+1)
    if not line.endswith(b"\n"):raise RuntimeError("Incomplete PowerPoint reply")
    reply=json.loads(line)
    if "error" in reply:raise ValueError(reply["error"])
    return reply["result"]


def validate_input(value,schema,where="arguments"):
    typ=schema.get("type")
    if not typ:return
    types={"object":dict,"array":list,"string":str,"integer":int,"number":(float,int),"boolean":bool,"null":type(None)}
    want=typ if isinstance(typ,list) else [typ]
    if not any(isinstance(value,types[t]) and (type(value) is not bool or t=="boolean") for t in want): raise ValueError(where+": expected "+str(typ))
    if isinstance(value,float) and not math.isfinite(value):raise ValueError(where+": expected a finite number")
    if "enum" in schema and value not in schema["enum"]:raise ValueError(where+": unexpected choice")
    if isinstance(value,dict):
        fields=schema.get("properties",{})
        for key in schema.get("required",[]):
            if key not in value:raise ValueError(where+" requires "+key)
        for key,item in value.items():
            if key in fields:validate_input(item,fields[key],where+"."+key)
            elif schema.get("additionalProperties",True) is False:raise ValueError(where+": unknown field "+key)
    if isinstance(value,list):
        if len(value)<schema.get("minItems",0):raise ValueError(where+": empty list")
        for i,item in enumerate(value):validate_input(item,schema.get("items",{}),where+"["+str(i)+"]")


def deck_overview(path,start,limit):
    with checked_zip(path.read_bytes()) as z:
        p="ppt/presentation.xml"
        rel=relationships(z,p)
        ids=parse(z.read(p)).findall("p:sldIdLst/p:sldId",NS)
        slides=[]
        for i,entry in enumerate(ids[start:start+limit],start+1):
            part=rel[entry.get(q("r:id"))]
            tree=parse(z.read(part))
            slides.append({"slide":i,"slideId":entry.get("id"),"text":[t.text for t in tree.iter(q("a:t"))][:120],
                           "shapes":len(tree.findall(".//p:cNvPr",NS))-1})
        return {"total":len(ids),"slides":slides,**chart_edit.inspect(path)}


class Service:
    def __init__(self,host=native,stage=None,validator=None):
        self.host=host
        self.reader=Reader()
        self.stage=stage
        self.validator=validator or ROOT/"SlidePilot.Validate.exe"

    def commit(self,ctx,name,data,review):
        output_path_for_check=Path(name)
        if output_path_for_check.name!=name or not re.fullmatch(r"[^/\\:*?\"<>|\x00-\x1f]{1,100}\.pptx",name,re.I):
            raise ValueError("Choose a .pptx filename without a directory")
        stage=Path(self.stage or os.environ["SLIDEPILOT_STAGE"]).resolve(strict=True)
        key=uuid.uuid4().hex
        path=stage/(key+".pptx")
        try:
            with path.open("xb") as dest:dest.write(data)
            checked=subprocess.run([str(self.validator),str(path)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                   timeout=120,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if checked.returncode:raise ValueError("Open XML validation failed: "+checked.stdout.decode(errors="replace")[:1600])
            result=self.host("mutate",binding=ctx["binding"],operation="commit_draft",args={
                "filename":name,"stage":key,"sha256":hashlib.sha256(data).hexdigest(),"review":review})
            return result
        finally:path.unlink(missing_ok=True)

    def call(self,name,args):
        if name not in TOOLS:raise ValueError("Unknown tool")
        validate_input(args,TOOLS[name]["inputSchema"])
        if name=="guide":
            result={"instructions":GUIDES[args["topic"]]}
            if args["topic"]=="formatting":
                result["liveMembers"]=json.loads((ROOT/"assets/chart-members.json").read_text(encoding="utf-8"))
            return result
        if name=="chart_catalog":
            term=args.get("query","").casefold()
            return {"types":[t for t in catalogue() if term in (t["type"]+" "+t["family"]).casefold()]}
        ctx=self.host("context")
        root=Path(ctx["workspace"])
        if name=="capabilities":
            version=int(ctx["version"].split(".")[0])
            return {"hostVersion":ctx["version"],"document":ctx["document"],"workspace":root.name,"automaticApproval":ctx["automatic"],
                    "classicDraftVariants":sum(g not in ("modern","recommended") for _,g in TYPES.values()),
                    "modernNativeProbe":version>=16,"recommendedTypeIsSentinel":True,"transport":"stdio",
                    "guidance":GUIDES["workflow"],"topics":list(GUIDES)}
        start=args.get("start",0);limit=args.get("limit",60)
        if start<0 or not 1<=limit<=200:raise ValueError("Use start >= 0 and limit 1..200")
        if name=="workspace_list":
            allfiles=list(files(root))
            return {"root":root.name,"total":len(allfiles),"files":allfiles[start:start+limit],"next":start+limit if start+limit<len(allfiles) else None}
        if name=="workspace_read":return self.reader.read(root,**args)
        if name=="draft_list":
            p=confined(root,DRAFTS+"/drafts",False)
            return {"files":[f.name for f in sorted(p.glob("*.pptx")) if f.is_file()]}
        if name in ("deck_inspect","chart_inspect","chart_patch_copy"):
            file=confined(root,args["file"])
            if file.suffix.lower()!=".pptx" or file.stat().st_size>128*1024*1024:raise ValueError("Select a workspace .pptx up to 128 MiB")
            if name=="deck_inspect":return deck_overview(file,start,limit)
            if name=="chart_inspect":return chart_edit.inspect(file,args.get("index"),start,limit,args.get("contains",""))
            data=chart_edit.patch(file,args["index"],args.get("edits",[]),args.get("cells",[]))
            return self.commit(ctx,args["filename"],data,{k:v for k,v in args.items() if k!="filename"})
        if name=="deck_compose":
            t=time.perf_counter()
            data,report=compose(root,self.reader,args["plan"])
            elapsed=round((time.perf_counter()-t)*1000,1)
            result=self.commit(ctx,args["filename"],data,args["plan"])
            return {**result,**report,"composeMs":elapsed}
        if name=="live_inspect":return self.host("inspect",binding=ctx["binding"],**args)
        if name=="live_chart_read":return self.host("chart_read",binding=ctx["binding"],**args)
        op={"live_chart_add":"chart_add","live_chart_patch":"chart_patch","live_chart_data":"chart_data",
            "live_slide_edit":"slide_edit","live_insert_draft":"insert_draft"}[name]
        if name=="live_chart_add":args={**args,"type":TYPES[canonical(args["type"])][0]}
        return self.host("mutate",binding=ctx["binding"],operation=op,args=args)


def response(service,msg):
    if (not isinstance(msg,dict) or msg.get("jsonrpc")!="2.0" or not isinstance(msg.get("method"),str)
            or ("id" in msg and not (msg["id"] is None or type(msg["id"]) in (str,int,float)))
            or (isinstance(msg.get("id"),float) and not math.isfinite(msg["id"]))):
        return {"jsonrpc":"2.0","id":None,"error":{"code":-32600,"message":"Invalid Request"}}
    if "id" not in msg:return None
    req={"jsonrpc":"2.0","id":msg["id"]}
    method=msg["method"];params=msg.get("params",{})
    # MCP named parameters must be an object. A malformed client frame must not
    # terminate the stdio process and strand the next otherwise valid request.
    if not isinstance(params,dict):
        return {**req,"error":{"code":-32602,"message":"Parameters must be an object"}}
    if method=="initialize":
        version=params.get("protocolVersion")
        result={"protocolVersion":version if version in VERSIONS else VERSIONS[0],"capabilities":{"tools":{"listChanged":False}},
                "serverInfo":{"name":"SlidePilot","version":"0.1.0-rc.3"},"instructions":GUIDES["workflow"]}
    elif method=="ping":result={}
    elif method=="tools/list":result={"tools":list(TOOLS.values())}
    elif method=="tools/call":
        if not isinstance(params.get("name"),str) or not isinstance(params.get("arguments",{}),dict):
            return {**req,"error":{"code":-32602,"message":"Use a tool name and an arguments object"}}
        try:
            result={"content":[{"type":"text","text":json.dumps(service.call(params["name"],params.get("arguments",{})),ensure_ascii=False,separators=(",",":"))}]}
        except Exception as e:result={"isError":True,"content":[{"type":"text","text":str(e)[:2400]}]}
    else:return {**req,"error":{"code":-32601,"message":"Method not found"}}
    return {**req,"result":result}


def main():
    service=Service()
    while True:
        line=sys.stdin.buffer.readline(8*1024*1024+1)
        if not line:break
        if len(line)>8*1024*1024:return 2
        try:reply=response(service,json.loads(line))
        except (UnicodeError,ValueError,RecursionError):reply={"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}}
        if reply is not None:
            sys.stdout.buffer.write((json.dumps(reply,ensure_ascii=False,separators=(",",":"))+"\n").encode())
            sys.stdout.buffer.flush()
    return 0

if __name__=="__main__":sys.exit(main())
