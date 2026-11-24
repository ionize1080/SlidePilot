import base64
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile

from fixtures import ROOT, small_plan
from package_xml import NS, parse, q, relationships, workbook
import reference_files as references
import reference_server
from reference_decks import compose_references, inspect_reference_deck
from test_workflow import workbook_cells


class ReferenceWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / 'Workspaces'
        self.store.mkdir()
        self.sources = self.root / 'sources'
        shutil.copytree(ROOT / 'examples/workspace', self.sources)
        self.workspace_id = 'a' * 32
        self.source_id = 'b' * 32
        self.grant = self.store / (self.workspace_id + '.json')
        self.grant.write_text(json.dumps(dict(id=self.workspace_id, sources=[dict(id=self.source_id, kind='folder', path=str(self.sources))], collections=[])), encoding='utf-8')
        patch = mock.patch.dict(os.environ, {'SLIDEPILOT_WORKSPACES': str(self.store)})
        patch.start()
        self.addCleanup(patch.stop)

    def identifier(self, name=''):
        return self.source_id + ':' + base64.urlsafe_b64encode(name.encode()).decode().rstrip('=')

    def plan(self):
        plan = small_plan()
        for slide in plan['slides']:
            for source in slide.get('sources', []):
                source['file_id'] = self.identifier(source.pop('file'))
                source['expected_revision'] = references.validated(self.workspace_id, source['file_id'])[1]
            if 'dataRef' in slide.get('chart', {}):
                ref = slide['chart']['dataRef']
                ref['file_id'] = self.identifier(ref.pop('file'))
                ref['expected_revision'] = references.validated(self.workspace_id, ref['file_id'])[1]
        return plan

    def test_listing_grants_virtual_folders_and_targeted_reads(self):
        root = references.list_files(self.workspace_id)
        self.assertFalse(root['contentIncluded'])
        self.assertEqual(root['entries'][0]['id'], self.identifier())
        files = references.list_files(self.workspace_id, self.identifier())
        self.assertEqual({x['name'] for x in files['entries']}, {'brief.md', 'deposits.csv'})
        source = references.read_file(self.workspace_id, self.identifier('deposits.csv'), start=5, count=1)
        self.assertEqual(source['units'][0]['location'], 'row 5')
        self.assertEqual(source['units'][0]['text'], 'Q4 | 142 | 94')
        self.assertNotIn(str(self.sources), json.dumps(source))
        found = references.find_files(self.workspace_id, query='deposits')
        self.assertEqual([x['name'] for x in found['entries']], ['deposits.csv'])

    def test_long_reference_continuation_is_lossless(self):
        text = 'A' * 5000 + '\nSecond line\n'
        (self.sources / 'long.txt').write_text(text, encoding='utf-8')
        next_page, result, stamp = dict(start=1, offset=0), '', None
        while next_page is not None:
            page = references.read_file(self.workspace_id, self.identifier('long.txt'), max_chars=1024,
                                        expected_revision=stamp, **next_page)
            stamp = page['revision']
            result += ''.join(unit['text'] for unit in page['units'])
            next_page = page['next']
        self.assertEqual(result, text)

    def test_revoked_grants_stale_revisions_and_traversal_are_rejected(self):
        identifier = self.identifier('brief.md')
        stamp = references.read_file(self.workspace_id, identifier)['revision']
        with (self.sources / 'brief.md').open('a', encoding='utf-8') as file:
            file.write('\nChanged evidence')
        with self.assertRaises(ValueError):
            references.read_file(self.workspace_id, identifier, expected_revision=stamp)
        with self.assertRaises(ValueError):
            references.resolve(self.workspace_id, self.identifier('../outside.txt'))
        self.grant.write_text(json.dumps(dict(id=self.workspace_id, sources=[], collections=[])), encoding='utf-8')
        with self.assertRaises(ValueError):
            references.read_file(self.workspace_id, identifier)

    def test_previous_chat_cannot_publish_under_new_chat_approval(self):
        def host(action, **arguments):
            self.assertEqual(action, 'context')
            return dict(binding='test-binding', workspace=str(self.sources), workspaceId='c' * 32)
        with self.assertRaisesRegex(ValueError, 'active chat workspace changed'):
            compose_references(self.workspace_id, 'Stale-chat.pptx', self.plan(), host)
        self.assertFalse(list((self.store / 'results' / self.workspace_id).glob('*.pptx')))

    def test_embedded_workbook_read_and_image_preview_use_bundled_dependencies(self):
        (self.sources / 'values.xlsx').write_bytes(workbook([['Quarter', 'Retail'], ['Q4', 142]]))
        rows = references.read_file(self.workspace_id, self.identifier('values.xlsx'), count=5)['units']
        self.assertEqual(rows[1]['location'], 'sheet Data row 2')
        self.assertIn('B2=142', rows[1]['text'])
        from PIL import Image
        with Image.new('RGB', (100, 50), '#19636c') as image:
            image.save(self.sources / 'image.png')
        preview = references.view_file(self.workspace_id, self.identifier('image.png'))
        self.assertEqual((preview['width'], preview['height'], preview['mimeType']), (100, 50, 'image/jpeg'))
        self.assertTrue(base64.b64decode(preview['data']).startswith(b'\xff\xd8'))

    def test_stdio_tools_and_worker_environment(self):
        frames = [dict(jsonrpc='2.0', id=1, method='initialize', params={'protocolVersion':'2025-03-26'}),
                  dict(jsonrpc='2.0', id=2, method='tools/list'),
                  dict(jsonrpc='2.0', id=3, method='tools/call', params=dict(name='workspace_read', arguments={
                      'workspace_id':self.workspace_id, 'file_id':self.identifier('deposits.csv'), 'start':5, 'count':1}))]
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'engine/reference_server.py')],
            input=''.join(json.dumps(frame) + '\n' for frame in frames).encode(), capture_output=True, timeout=20, check=True)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertIn('reference_deck_compose', [t['name'] for t in replies[1]['result']['tools']])
        self.assertEqual(json.loads(replies[2]['result']['content'][0]['text'])['units'][0]['text'], 'Q4 | 142 | 94')
        self.assertEqual(result.stderr, b'')
        original = subprocess.Popen
        observed = []
        def checked(*args, **kwargs):
            observed.append(kwargs['env'])
            return original(*args, **kwargs)
        with mock.patch.dict(os.environ, {'SLIDEPILOT_UI_TOKEN':'must-not-reach-parser', 'FAKE_API_KEY':'must-not-reach-parser'}), \
             mock.patch.object(reference_server.subprocess, 'Popen', side_effect=checked):
            reference_server.worker('list', {'workspace_id':self.workspace_id})
        self.assertNotIn('SLIDEPILOT_UI_TOKEN', observed[0])
        self.assertNotIn('FAKE_API_KEY', observed[0])
        self.assertNotIn('SLIDEPILOT_TOKEN', observed[0])

    def test_harbour_references_to_reviewed_ppt_preserves_data_notes_and_originals(self):
        validator = ROOT / '.build/qa/Validate.exe'
        if not validator.exists():
            self.skipTest('Office 2010 validator is not built on this machine')
        stage = self.root / 'stage'
        stage.mkdir()
        drafts = self.root / 'host-drafts'
        drafts.mkdir()
        originals = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.sources.iterdir()}
        calls = []
        def host(action, **arguments):
            if action == 'context':
                return dict(binding='test-binding', workspace=str(self.sources))
            self.assertEqual((action, arguments['operation'], arguments['binding']), ('mutate', 'commit_draft', 'test-binding'))
            args = arguments['args']
            raw = (stage / (args['stage'] + '.pptx')).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), args['sha256'])
            self.assertEqual(args['review']['workspace_id'], self.workspace_id)
            (drafts / args['filename']).write_bytes(raw)
            calls.append(args)
            return dict(file='_SlidePilot/drafts/' + args['filename'], sha256=args['sha256'])
        plan = self.plan()
        reference_server.validate_input({'workspace_id':self.workspace_id, 'filename':'Harbour.pptx', 'plan':plan},
            reference_server.TOOLS['reference_deck_compose']['inputSchema'])
        result = compose_references(self.workspace_id, 'Harbour.pptx', plan, host, stage, validator)
        path, _ = references.validated(self.workspace_id, result['file_id'])
        self.assertEqual(path.read_bytes(), (drafts / 'Harbour.pptx').read_bytes())
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(stage.iterdir()), [])
        self.assertTrue(result['workspaceCopySaved'])
        self.assertEqual(inspect_reference_deck(self.workspace_id, result['file_id'])['total'], 3)
        with ZipFile(path) as deck:
            chart = parse(deck.read('ppt/charts/chart1.xml'))
            book = relationships(deck, 'ppt/charts/chart1.xml')['rIdBook']
            cells = workbook_cells(deck.read(book))
            self.assertEqual([float(cells['B' + str(i)]) for i in range(2, 6)], [100, 116, 128, 142])
            self.assertEqual([float(cells['C' + str(i)]) for i in range(2, 6)], [82, 85, 91, 94])
            notes = deck.read('ppt/notesSlides/notesSlide2.xml').decode()
            self.assertIn('Q4 | 142 | 94', notes)
            self.assertIn('deposits.csv', notes)
            self.assertNotIn('source002.csv', notes)
            for series, expected in zip(chart.findall('.//c:ser', NS), ([100,116,128,142], [82,85,91,94])):
                values = [float(n.text) for n in series.findall('c:val/c:numRef/c:numCache/c:pt/c:v', NS)]
                self.assertEqual(values, expected)
        self.assertEqual(originals, {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.sources.iterdir()})
        validated = subprocess.run([str(validator), str(path)], capture_output=True, check=True, timeout=30)
        self.assertIn(b'errors: 0', validated.stdout)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            compose_references(self.workspace_id, 'Harbour.pptx', plan, host, stage, validator)
        self.assertEqual(len(calls), 1)

    def test_bad_citations_and_denied_review_never_publish_chat_results(self):
        validator = ROOT / '.build/qa/Validate.exe'
        if not validator.exists():
            self.skipTest('Office 2010 validator is not built on this machine')
        stage = self.root / 'stage'
        stage.mkdir()
        calls = []
        def host(action, **arguments):
            if action == 'context':
                return dict(binding='test-binding', workspace=str(self.sources))
            calls.append(arguments)
            raise ValueError('User denied this operation. Wait for new instructions.')
        plan = self.plan()
        plan['slides'][1]['sources'][0]['quote'] = 'Invented deposit total'
        with self.assertRaisesRegex(ValueError, 'quote does not match'):
            compose_references(self.workspace_id, 'Rejected.pptx', plan, host, stage, validator)
        self.assertFalse(calls)
        with self.assertRaisesRegex(ValueError, 'User denied'):
            compose_references(self.workspace_id, 'Rejected.pptx', self.plan(), host, stage, validator)
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(stage.iterdir()), [])
        self.assertEqual(list((self.store / 'results' / self.workspace_id).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
