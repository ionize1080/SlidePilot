"""Export the committed project and its pinned upstream Chatbox source for redistribution."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZIP_STORED, ZipFile

from build_portable import DIST, ROOT, VERSION
from prepare_chatbox import COMMIT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream",type=Path,default=ROOT/".build/chatbox-upstream.zip")
    args=parser.parse_args()
    with ZipFile(args.upstream) as source:
        if source.comment!=COMMIT.encode() or "src/main/main.ts" not in source.namelist():
            raise ValueError("Expected the pinned Chatbox git archive")
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    DIST.mkdir(exist_ok=True)
    dest=DIST/f"SlidePilot-{VERSION}-source.zip"
    with tempfile.TemporaryDirectory(dir=DIST) as tmp:
        archive=Path(tmp)/"source.zip"
        subprocess.run(["git","archive","--format=zip","--prefix=SlidePilot/","-o",str(archive),commit],cwd=ROOT,check=True)
        with ZipFile(archive,"a") as z:
            z.write(args.upstream,"SlidePilot/vendor/chatbox-upstream.zip",compress_type=ZIP_STORED)
            z.writestr("SlidePilot/SOURCE-COMMIT.txt",commit+"\n")
        archive.replace(dest)
    print(dest.name,commit)


if __name__=="__main__":
    main()
