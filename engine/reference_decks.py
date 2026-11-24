"""Compose from chat-granted references through the existing PowerPoint review path."""
from copy import deepcopy
import hashlib
from pathlib import Path, PureWindowsPath
import re
import tempfile
import time
import uuid

import reference_files as references
from decks import compose, publish_new
from server import Service, deck_overview, native
from workspace import Reader


def result_folder(workspace_id):
    references.workspace(workspace_id)
    root = references.home()
    folder = root / 'results' / workspace_id
    for part in [folder, *folder.parents]:
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Presentation output cannot use links or junctions')
        if part == root:
            break
    folder.mkdir(parents=True, exist_ok=True)
    if not folder.resolve().is_relative_to(root):
        raise ValueError('Presentation output left the current workspace')
    return folder


class EvidenceReader(Reader):
    def __init__(self, evidence):
        super().__init__()
        self.evidence = evidence

    def source_label(self, file):
        return self.evidence[file]['name']

    def cite(self, root, source):
        item = self.evidence[source['file']]
        quote = source['quote'].strip()
        matched = False
        iterator = references.units(Path(root) / source['file'])
        try:
            for locator, text in iterator:
                if locator == source['locator'] and quote and quote in text:
                    matched = True
                    break
        finally:
            iterator.close()
        if not matched:
            raise ValueError('Source quote does not match its locator: ' + item['name'] + ' ' + source['locator'])
        if source.get('sha256', item['sha256']) != item['sha256']:
            raise ValueError('Source hash no longer matches ' + item['name'])
        return item['name'] + ' — ' + source['locator'] + ' — ' + quote


def compose_references(workspace_id, filename, plan, host=native, stage=None, validator=None):
    if (not isinstance(filename, str) or not re.fullmatch(r'[^/\\:*?"<>|\x00-\x1f]{1,100}\.pptx', filename, re.I)
            or PureWindowsPath(filename).is_reserved()):
        raise ValueError('Choose one non-reserved .pptx filename without a directory')
    folder = result_folder(workspace_id)
    if (folder / filename).exists():
        raise ValueError('A presentation with this name already exists in this chat; choose a new filename')
    context = host('context')
    if 'workspaceId' in context and context['workspaceId'] != workspace_id:
        raise ValueError('The active chat workspace changed. Return to the current chat and read its workspace again.')
    started = time.perf_counter()
    plan = deepcopy(plan)
    evidence, selected, total = {}, {}, 0
    with tempfile.TemporaryDirectory(prefix='slidepilot-references-') as temporary:
        snapshot = Path(temporary)

        def materialize(reference):
            nonlocal total
            identifier = reference['file_id']
            path, stamp = references.validated(workspace_id, identifier, reference.get('expected_revision'))
            if identifier not in selected:
                if len(selected) >= 100 or path.stat().st_size > 64 * 1024 * 1024:
                    raise ValueError('Compose from up to 100 references, each at most 64 MiB')
                raw = path.read_bytes()
                total += len(raw)
                if total > 256 * 1024 * 1024:
                    raise ValueError('Selected references exceed the 256 MiB composition limit')
                references.validated(workspace_id, identifier, stamp)
                alias = f'source{len(selected) + 1:03d}' + path.suffix.lower()
                (snapshot / alias).write_bytes(raw)
                evidence[alias] = dict(file_id=identifier, name=path.name, revision=stamp,
                                       sha256=hashlib.sha256(raw).hexdigest())
                selected[identifier] = alias
            alias = selected[identifier]
            item = evidence[alias]
            if stamp != item['revision']:
                raise ValueError('A reference changed during composition; read it again')
            if reference.get('sha256', item['sha256']) != item['sha256']:
                raise ValueError('A reference hash changed; read it again')
            reference.pop('file_id')
            reference.pop('expected_revision', None)
            reference['file'] = alias
            return alias

        for slide in plan['slides']:
            for source in slide.get('sources', []):
                materialize(source)
            chart = slide.get('chart', {})
            if 'dataRef' in chart:
                alias = materialize(chart['dataRef'])
                chart['dataRef']['sha256'] = evidence[alias]['sha256']
                # Keep the human source name in notes instead of only the private snapshot alias.
                slide['notes'] = (slide.get('notes', '') + '\nChart data: ' + evidence[alias]['name']).strip()
            if 'image' in slide:
                materialize(slide['image'])
        compose_started = time.perf_counter()
        data, report = compose(snapshot, EvidenceReader(evidence), plan)
        compose_ms = round((time.perf_counter() - compose_started) * 1000, 1)
        for item in evidence.values():
            references.validated(workspace_id, item['file_id'], item['revision'])
        review = dict(workspace_id=workspace_id, sources=list(evidence.values()), slides=len(plan['slides']), filename=filename, plan=plan)
        result = Service(host=host, stage=stage, validator=validator).commit(context, filename, data, review)
    # Publication above is approved and schema-validated. Retain an identical chat
    # copy so the workspace can open/export it without changing the host draft.
    target = folder / filename
    try:
        try:
            publish_new(target, data)
        except FileExistsError:
            target = folder / (Path(filename).stem + '-' + uuid.uuid4().hex[:8] + '.pptx')
            publish_new(target, data)
    except OSError:
        return {**result, **report, 'workspaceCopySaved': False,
                'warning': 'PowerPoint draft was published, but the chat copy could not be retained. Open it from the host draft folder.',
                'sources': list(evidence.values())}
    return {**result, **report, 'workspace_id': workspace_id,
            'file_id': references.file_id({'id': 'results'}, target.name), 'name': target.name,
            'workspaceCopySaved': True, 'sources': list(evidence.values()),
            'composeMs': compose_ms, 'elapsedMs': round((time.perf_counter() - started) * 1000, 1)}


def inspect_reference_deck(workspace_id, file_id, start=0, limit=60, expected_revision=None):
    path, stamp = references.validated(workspace_id, file_id, expected_revision)
    if path.suffix.lower() != '.pptx' or path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Select a PPTX up to 128 MiB')
    if type(start) is not int or start < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('Use start >= 0 and limit 1..200')
    result = deck_overview(path, start, limit)
    references.validated(workspace_id, file_id, stamp)
    return dict(result, file_id=file_id, revision=stamp)
