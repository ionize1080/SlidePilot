"""Offline chat-workspace-to-PPT integration; approval is a fixture, never a real API call."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import ROOT, small_plan
import reference_files as references
from reference_decks import compose_references, inspect_reference_deck
from package_xml import NS, parse, relationships
from test_workflow import workbook_cells


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validator', type=Path, default=ROOT / 'dist/SlidePilot/SlidePilot.Validate.exe')
    parser.add_argument('--output', type=Path, default=ROOT / '.build/qa/Reference-Workspace-Harbour.pptx')
    args = parser.parse_args()
    workspace_id, source_id = 'a' * 32, 'b' * 32
    with tempfile.TemporaryDirectory(prefix='slidepilot-reference-smoke-') as temporary:
        temporary = Path(temporary)
        store, stage, source = temporary / 'workspaces', temporary / 'stage', temporary / 'source'
        store.mkdir(); stage.mkdir()
        shutil.copytree(ROOT / 'examples/workspace', source)
        originals = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
        (store / (workspace_id + '.json')).write_text(json.dumps(dict(id=workspace_id, sources=[dict(id=source_id, kind='folder', path=str(source))], collections=[])), encoding='utf-8')
        old = os.environ.get('SLIDEPILOT_WORKSPACES')
        os.environ['SLIDEPILOT_WORKSPACES'] = str(store)
        committed = []
        try:
            def host(action, **arguments):
                if action == 'context':
                    return dict(binding='fixture', workspace=str(source), workspaceId=workspace_id)
                assert action == 'mutate' and arguments['operation'] == 'commit_draft'
                value = arguments['args']
                raw = (stage / (value['stage'] + '.pptx')).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == value['sha256']
                committed.append(raw)
                return dict(file='_SlidePilot/drafts/' + value['filename'], sha256=value['sha256'])
            plan = small_plan()
            for slide in plan['slides']:
                refs = list(slide.get('sources', []))
                if 'dataRef' in slide.get('chart', {}): refs.append(slide['chart']['dataRef'])
                for ref in refs:
                    ref['file_id'] = references.file_id({'id':source_id}, ref.pop('file'))
                    ref['expected_revision'] = references.validated(workspace_id, ref['file_id'])[1]
            result = compose_references(workspace_id, 'Harbour.pptx', plan, host, stage, args.validator.resolve())
            output, _ = references.validated(workspace_id, result['file_id'])
            assert len(committed) == 1 and output.read_bytes() == committed[0] and not list(stage.iterdir())
            assert inspect_reference_deck(workspace_id, result['file_id'])['total'] == 3
            rows = list(csv.reader((source / 'deposits.csv').read_text().splitlines()))
            expected = [[float(row[column]) for row in rows[1:]] for column in (1,2)]
            with ZipFile(output) as deck:
                drawing = parse(deck.read('ppt/charts/chart1.xml'))
                cells = workbook_cells(deck.read(relationships(deck, 'ppt/charts/chart1.xml')['rIdBook']))
                actual = [[float(cells[column + str(row)]) for row in range(2,6)] for column in ('B','C')]
                assert actual == expected
                series = [[float(node.text) for node in item.findall('c:val/c:numRef/c:numCache/c:pt/c:v', NS)] for item in drawing.findall('.//c:ser', NS)]
                assert series == expected
                notes = deck.read('ppt/notesSlides/notesSlide2.xml').decode()
                assert 'deposits.csv' in notes and 'Q4 | 142 | 94' in notes and 'source002.csv' not in notes
            assert originals == {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
            subprocess.run([str(args.validator.resolve()), str(output)], check=True)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output, args.output)
            print(json.dumps(dict(mode='offline integration with fixture approval', output=str(args.output.resolve()), slides=3,
                series=expected, sourceHashesUnchanged=True, hostCopyMatches=True, composeMs=result['composeMs']), ensure_ascii=False))
        finally:
            if old is None: os.environ.pop('SLIDEPILOT_WORKSPACES', None)
            else: os.environ['SLIDEPILOT_WORKSPACES'] = old


if __name__ == '__main__':
    main()
