"""Bounded offline evidence ZIPs. Inventory hashes are not source authentication.

All conclusions and projections are recomputed from packaged primary evidence.
The original separately supplied C14 package has an explicit legacy reader.
"""
import argparse
import hashlib
import io
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from contextlib import contextmanager

from .evidence import Schema, _hash, _timestamp
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, parts, strict_json, _directory
from .review_packet_io import atomic_create, outside

MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_FILES = 256
MANIFEST = 'package-manifest.json'
INDEX = 'evidence-index.json'


def path_parts(name):
    values = parts(name)
    if (len(name) > 240 or len(values) > 12 or not name.isascii()
        or any(p.startswith('.') or p.endswith('.partial') or '%' in p for p in values)):
        raise EvidenceError('unsupported_package_path')
    return values


@dataclass(frozen=True, kw_only=True)
class EvidencePackageManifest(Schema):
    phase: str
    profile: str
    files_json: str
    recipe: str = 'cases.json'
    evidence_index: str = INDEX
    rule_version: str = 'evidence-package-v1'

    def validate(self):
        files = strict_json(self.files_json.encode())
        if (self.phase not in ('C14', 'C15', 'C16', 'C17') or self.profile not in ('live', 'synthetic')
            or self.recipe != 'cases.json' or self.evidence_index != INDEX
            or self.rule_version != 'evidence-package-v1' or type(files) is not dict
            or not 1 <= len(files) < MAX_FILES or canonical(files) != self.files_json
            or MANIFEST in files or INDEX not in files or self.recipe not in files):
            raise ValueError('versioned_bounded_package_manifest_required')
        for name, sha in files.items():
            path_parts(name)
            if type(sha) is not str:
                raise ValueError('literal_package_digest_required')
            _hash(sha)


def _relative(root, value):
    if type(value) is not str:
        raise EvidenceError('literal_package_relative_path_required')
    path_parts(value)
    return str(Path(root).joinpath(*parts(value)))


def _recipe(root, phase):
    with EvidenceRoot(root, max_bytes=MAX_FILE, max_total_bytes=MAX_TOTAL, max_files=MAX_FILES) as reader:
        raw = reader.read('cases.json').data
    if len(raw) > 1048576:
        raise EvidenceError('package_recipe_size_limit')
    value = strict_json(raw)
    baseline = None
    if phase in ('C15', 'C16', 'C17'):
        if (type(value) is not dict or set(value) != ({'schema_version', 'cases', 'baseline_package', 'selected_action'} if phase == 'C17' else {'schema_version', 'cases', 'baseline_package'})
            or type(value['schema_version']) is not int or value['schema_version'] != 1):
            raise EvidenceError('explicit_C15_package_recipe_required')
        baseline = _relative(root, value['baseline_package'])
        value = value['cases']
    if type(value) is not list or not 1 <= len(value) <= (3 if phase == 'C17' else 2):
        raise EvidenceError('one_or_two_packaged_case_recipes_required')
    cases, primary_roots = [], []
    for case in value:
        if type(case) is not dict:
            raise EvidenceError('explicit_packaged_case_required')
        resolved = dict(case)
        for key in ('collections', 'sam_captures'):
            if key in case:
                if type(case[key]) is not list:
                    raise EvidenceError('explicit_package_root_sequence_required')
                resolved[key] = [_relative(root, p) for p in case[key]]
                primary_roots.extend(case[key])
        for key in ('c12_capture', 'historical_probe', 'parent_history', 'continuation', 'authority_binding', 'new_parent_capture', 'new_parent_history', 'report'):
            if case.get(key) is not None:
                resolved[key] = _relative(root, case[key])
                primary_roots.append(case[key])
        cases.append(resolved)
    if any(p in ('report', 'cases.json', INDEX, MANIFEST) or p.startswith('report/') for p in primary_roots):
        raise EvidenceError('primary_roots_cannot_alias_generated_package_output')
    return cases, baseline, primary_roots


def _replay(root, phase):
    cases, baseline, roots = _recipe(root, phase)
    if phase == 'C14':
        from .correction_reporting import verify_report
        value = verify_report(Path(root) / 'report', cases)
    elif phase == 'C15':
        from .parent_coverage_reporting import verify_report
        value = verify_report(Path(root) / 'report', cases, baseline_package=baseline)
    elif phase == 'C16':
        from .authority_reporting import verify_report
        value = verify_report(Path(root) / 'report', cases, baseline_package=baseline)
    else:
        from .parent_authority_reporting import verify_report
        with EvidenceRoot(root) as reader:
            selection = strict_json(reader.read('cases.json').data)['selected_action']
        value = verify_report(Path(root) / 'report', cases, baseline_package=baseline, selected_action=selection)
    return value, roots


def _index(root, phase, value):
    c16 = value['baseline'] if phase == 'C17' else value
    c15 = c16['baseline'] if phase in ('C16', 'C17') else c16
    c14 = c15['baseline'] if phase in ('C15', 'C16', 'C17') else c15
    cases = c14['cases']
    captures = []
    for case in cases:
        parent = case['parent_probe']
        if parent is not None:
            captures.append({'role': 'C14_parent', 'inventory_sha256': parent['inventory_sha256'],
                'profile': parent['profile'], 'selection': parent['selection'],
                'capture_contract_version': parent['capture_contract_version'],
                'reassessment_contract_version': parent['record_reassessment']['rule_version'],
                'original_failures': parent['failures'], 'pagination': parent['pagination'],
                'records': parent['record_reassessment']['records'],
                'historical_applicability': 'unknown'})
    if phase in ('C15', 'C16', 'C17'):
        for case in c15['cases']:
            if case['continuation'] is not None:
                captures.append({'role': 'C15_continuation', **case['continuation']})
    if phase in ('C16', 'C17'):
        captures.extend({'role': 'C16_child_parent_binding', **c['binding']} for c in c16['cases'] if c['binding'] is not None)
    if phase == 'C17':
        captures.extend({'role': 'C17_parent', **c['new_parent_probe']} for c in value['cases'] if c['new_parent_probe'] is not None)
        captures.extend({'role': 'C17_child_parent', **c['child_parent_capture']} for c in value['cases'] if c['child_parent_capture'] is not None)
    requests = []
    with EvidenceRoot(root, max_bytes=MAX_FILE, max_total_bytes=MAX_TOTAL, max_files=MAX_FILES) as reader:
        for name in reader.discover():
            if re.search(r'/(?:parent|continuation|binding|detail|page|c3_attempt)[-_][0-9]{3,6}\.json$', name):
                meta = strict_json(reader.read(name).data)
                requests.append({'package_metadata_path': name, **meta})
    return {'schema_type': 'EvidencePackageIndex', 'schema_version': 1, 'phase': phase,
        'profile': value['profile'], 'qualification_scope': 'packaged_cases_only_not_unincluded_cohort',
        'primary_requests': requests, 'source_captures': captures, 'report_sha256': digest(value),
        'limitations': ['hashes_not_upstream_authentication', 'replay_not_new_acquisition',
            'terminal_pages_not_complete_history', 'parent_record_not_historical_applicability',
            'no_financial_authorization']}


def _allowed(names, roots, phase):
    auxiliary = {'README.txt', 'cases.json', INDEX, MANIFEST}
    if phase in ('C15', 'C16', 'C17'):
        auxiliary.add('baseline-package.zip')
    # Original C14 exports included these public documentation snapshots.
    docs = ('usa-transactions', 'usa-deletion-implementation', 'fpds-correction-help', 'sam-guide')
    auxiliary.update('official-documents/' + n + ext for n in docs for ext in ('.body', '.json'))
    if phase in ('C16', 'C17'):
        auxiliary.update('official-documents/usa-award-detail' + ext for ext in ('.body', '.json'))
    auxiliary.update('protocols/' + n for n in ('correction-parent-protocol-v1.json',
        'correction-source-capabilities-v1.json', 'correction-parent-evidence.md'))
    for name in names:
        path_parts(name)
        if name in auxiliary or name.startswith('report/'):
            continue
        if any(name.startswith(p + '/') for p in roots):
            basename = parts(name)[-1]
            fixed = {'c3_plan.json', 'c3_checkpoint.json', 'c3_summary.json', 'pilot-plan.json',
                'experiment.json', 'experiment-commit.json', 'parent-commit.json',
                'probe-commit.json', 'continuation-commit.json', 'sam-result.json',
                'binding-commit.json',
                'sam-research-commit.json', 'qualification.json', 'qualification.md',
                'qualification.html', 'qualification-commit.json'}
            if basename in fixed or re.fullmatch(r'(?:c3_attempt_[0-9]{6}|(?:detail|parent|page|continuation|binding)-[0-9]{3}(?:-reservation)?|sam-attempt-[0-9]{3}(?:-reserved)?)\.(?:json|body)', basename):
                continue
        raise EvidenceError('undeclared_package_member')


def _verify_directory(root, phase, *, legacy=False, expected_profile=None):
    with EvidenceRoot(root, max_bytes=MAX_FILE, max_total_bytes=MAX_TOTAL, max_files=MAX_FILES) as reader:
        before = {n: reader.read(n).byte_sha256 for n in reader.discover()}
    value, roots = _replay(root, phase)
    if phase in ('C16', 'C17'):
        from .authority_binding import PARENT_DOCUMENTATION
        body_name = 'official-documents/usa-award-detail.body'
        meta_name = 'official-documents/usa-award-detail.json'
        if value['profile'] == 'live' or body_name in before or meta_name in before:
            with EvidenceRoot(root, max_bytes=MAX_FILE) as reader:
                body, meta = reader.read(body_name), strict_json(reader.read(meta_name).data)
            if (type(meta) is not dict or set(meta) != {'request', 'status', 'retrieved_at_utc', 'body_complete', 'sha256', 'representation', 'location'}
                or type(meta.get('retrieved_at_utc')) is not str or meta.get('location') is not None
                or body.byte_sha256 != PARENT_DOCUMENTATION['body_sha256']
                or meta.get('request') != {'method': 'GET', 'url': PARENT_DOCUMENTATION['url'], 'redirects': False}
                or meta.get('status') != 200 or meta.get('body_complete') is not True
                or meta.get('sha256') != body.byte_sha256
                or meta.get('representation') != 'HTTP_entity_bytes_after_content_decoding'):
                raise EvidenceError('C16_source_contract_document_conflict')
            _timestamp(meta['retrieved_at_utc'])
    _allowed(before, roots, phase)
    if expected_profile is not None and value['profile'] != expected_profile:
        raise EvidenceError('package_profile_conflict')
    index = _index(root, phase, value)
    if not legacy:
        with EvidenceRoot(root, max_bytes=MAX_FILE, max_total_bytes=MAX_TOTAL, max_files=MAX_FILES) as reader:
            if reader.read(INDEX).data != (canonical(index) + '\n').encode():
                raise EvidenceError('package_index_primary_replay_conflict')
    with EvidenceRoot(root, max_bytes=MAX_FILE, max_total_bytes=MAX_TOTAL, max_files=MAX_FILES) as reader:
        if {n: reader.read(n).byte_sha256 for n in reader.discover()} != before:
            raise EvidenceError('package_primary_changed_during_replay')
    resolved = value['resolved_original_real_source_requirements'] if phase == 'C14' else value['previously_resolved_real_source_requirements'] + value['newly_resolved_real_source_requirements']
    c14 = value if phase == 'C14' else value['baseline'] if phase == 'C15' else value['baseline']['baseline'] if phase == 'C16' else value['baseline']['baseline']['baseline']
    return {'schema_type': 'EvidencePackageVerification', 'schema_version': 1, 'phase': phase,
        'profile': value['profile'], 'format': 'explicit_legacy_C14_v1' if legacy else 'evidence-package-v1',
        'package_files': before, 'report_sha256': digest(value), 'evidence_index_sha256': digest(index),
        'qualification_scope': 'packaged_cases_only_not_unincluded_cohort',
        'verified_case_bindings': [{'original_case_sha256': c['original_case_sha256'],
            'parent_inventory_sha256': None if c['parent_probe'] is None else c['parent_probe']['inventory_sha256']}
            for c in c14['cases']],
        'resolved_real_source_plan_ids': sorted(set(resolved)),
        'remaining_plan_ids': value['remaining_original_plan_ids'],
        'primary_replay': 'verified', 'financial_comparison_authorized': False}


def _raw_archive(path):
    source = Path(path).absolute()
    with EvidenceRoot(source.parent, max_bytes=MAX_FILE) as reader:
        saved = reader.read(source.name)
        reader.read(source.name, recheck=True)
    return saved.data


def _inspect(raw, expected_phase):
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        infos = archive.infolist()
        if not 1 <= len(infos) <= MAX_FILES or sum(i.file_size for i in infos) > MAX_TOTAL:
            raise EvidenceError('package_archive_size_or_count_limit')
        names = []
        for info in infos:
            path_parts(info.filename)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if (info.orig_filename != info.filename or info.is_dir() or mode not in (0, stat.S_IFREG) or info.flag_bits & 1
                or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or info.file_size > MAX_FILE or info.file_size > max(1, info.compress_size) * 200):
                raise EvidenceError('unsafe_package_member_or_compression')
            names.append(info.filename)
        if len(set(n.casefold() for n in names)) != len(names) or MANIFEST not in names:
            raise EvidenceError('duplicate_or_missing_package_manifest')
        if any('/'.join(parts(n)[:i]) in names for n in names for i in range(1, len(parts(n)))):
            raise EvidenceError('package_file_directory_collision')
        manifest = strict_json(archive.read(MANIFEST))
        if type(manifest) is not dict:
            raise EvidenceError('package_manifest_object_required')
        legacy = set(manifest) == {'schema_version', 'files'}
        if legacy:
            if type(manifest['schema_version']) is not int or manifest['schema_version'] != 1 or type(manifest['files']) is not dict:
                raise EvidenceError('unsupported_legacy_package_manifest')
            phase, profile, files = 'C14', None, manifest['files']
        else:
            model = EvidencePackageManifest.from_dict(manifest)
            phase, profile, files = model.phase, model.profile, strict_json(model.files_json.encode())
        if expected_phase is not None and phase != expected_phase:
            raise EvidenceError('unexpected_package_phase_no_recursive_admission')
        if set(files) != set(names) - {MANIFEST}:
            raise EvidenceError('package_inventory_not_exact')
        for name, expected in files.items():
            path_parts(name)
            if type(expected) is not str:
                raise EvidenceError('literal_package_digest_required')
            _hash(expected)
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise EvidenceError('package_member_digest_conflict')
        return archive, phase, profile, legacy
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error):
        raise EvidenceError('malformed_or_unsupported_evidence_zip') from None


@contextmanager
def verified_directory(path, *, expected_phase=None):
    """Yield a private, verified copy for scoped primary reads; never a trust
    assertion about upstream authenticity. No extraction path escapes receipts.
    """
    raw = _raw_archive(path)
    archive, phase, profile, legacy = _inspect(raw, expected_phase)
    try:
        with tempfile.TemporaryDirectory(prefix='fsa-package-') as temporary:
            for name in sorted(archive.namelist()):
                components = path_parts(name)
                fd = _directory(Path(temporary))
                try:
                    for part in components[:-1]:
                        try:
                            os.mkdir(part, 0o700, dir_fd=fd)
                        except FileExistsError:
                            pass
                        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        os.close(fd)
                        fd = child
                    atomic_create(fd, components[-1], archive.read(name))
                finally:
                    os.close(fd)
            result = _verify_directory(temporary, phase, legacy=legacy, expected_profile=profile)
            yield Path(temporary), {**result, 'archive_sha256': hashlib.sha256(raw).hexdigest()}
    finally:
        archive.close()


def verify_package(path, *, expected_phase=None):
    with verified_directory(path, expected_phase=expected_phase) as (_, result):
        return result


def build_package(directory, output, *, phase='C14'):
    """Export an explicit self-contained staging directory, never a workspace."""
    if phase not in ('C14', 'C15', 'C16', 'C17'):
        raise EvidenceError('supported_package_phase_required')
    outside(output, (directory,))
    with EvidenceRoot(directory, max_bytes=MAX_FILE, max_total_bytes=MAX_TOTAL, max_files=MAX_FILES) as reader:
        values = {n: reader.read(n).data for n in reader.discover() if n not in (MANIFEST, INDEX)}
    value, roots = _replay(directory, phase)
    _allowed(values, roots, phase)
    values[INDEX] = (canonical(_index(directory, phase, value)) + '\n').encode()
    model = EvidencePackageManifest(phase=phase, profile=value['profile'],
        files_json=canonical({n: hashlib.sha256(b).hexdigest() for n, b in values.items()}))
    values[MANIFEST] = (model.to_json() + '\n').encode()
    output_bytes = io.BytesIO()
    with zipfile.ZipFile(output_bytes, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, body in sorted(values.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, body)
    raw = output_bytes.getvalue()
    if len(raw) > MAX_FILE:
        raise EvidenceError('compressed_package_size_limit')
    # Full primary replay of a temporary archive before publishing any output.
    with tempfile.TemporaryDirectory(prefix='fsa-package-build-') as temporary:
        candidate = Path(temporary) / 'candidate.zip'
        candidate.write_bytes(raw)
        result = verify_package(candidate, expected_phase=phase)
    target = Path(output).absolute()
    fd = _directory(target.parent)
    try:
        atomic_create(fd, target.name, raw)
    finally:
        os.close(fd)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline primary-replayed evidence package verifier/exporter.')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--verify-package')
    mode.add_argument('--build-from')
    parser.add_argument('--output')
    parser.add_argument('--phase', choices=('C14', 'C15', 'C16', 'C17'), default='C14')
    args = parser.parse_args(argv)
    try:
        if args.verify_package:
            if args.output:
                raise EvidenceError('verification_does_not_extract_into_user_directories')
            value = verify_package(args.verify_package)
        else:
            if not args.output:
                raise EvidenceError('explicit_new_archive_output_required')
            value = build_package(args.build_from, args.output, phase=args.phase)
        # Exact member inventory, case scope and reconstructed result are part
        # of the verification receipt; no private extraction path is emitted.
        print(canonical(value))
        return 0
    except (ValueError, OSError, KeyError, IndexError, TypeError, zipfile.BadZipFile):
        print(canonical({'error_code': 'evidence_package_rejected', 'exit_code': 2}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
