"""Opt-in offline coordinator rehearsal CLI; no actual human enrollment mode."""
import argparse
from pathlib import Path
from .evidence_io import EvidenceError, EvidenceRoot, canonical, strict_json
from .pilot_session_store import _private_fd
from .coordinator_governance import CoordinatorChecklist
from .coordinator_rehearsal import exercise
from .coordinator_lifecycle import inspect, tip, retire, delete
from .coordinator_reporting import write_report


def main(argv=None):
    p=argparse.ArgumentParser(description='Offline simulated coordinator rehearsal. No human enrollment or financial authority.')
    mode=p.add_mutually_exclusive_group(required=True)
    for flag in ('rehearse','retire','delete','report'):mode.add_argument('--'+flag,action='store_true')
    p.add_argument('--store',required=True);p.add_argument('--coordinator-key');p.add_argument('--study-root');p.add_argument('--public-root')
    p.add_argument('--output');p.add_argument('--as-of',required=True);p.add_argument('--expected-tip');p.add_argument('--checklist')
    p.add_argument('--reason',choices=['DRY_RUN','WITHDRAWAL_REQUEST','RETENTION_EXPIRED'],default='WITHDRAWAL_REQUEST')
    a=p.parse_args(argv)
    try:
        key=a.coordinator_key
        if a.rehearse:
            if not a.study_root or not a.public_root:raise EvidenceError('exact_mixed_plan_inputs_required')
            key=exercise(a.store,a.study_root,a.public_root,as_of=a.as_of)
        elif key is None:raise EvidenceError('coordinator_capability_required')
        checklist=None
        if a.checklist:
            target=Path(a.checklist).absolute()
            with EvidenceRoot(target.parent,max_bytes=65536) as root:
                _private_fd(root.fd);checklist=CoordinatorChecklist.from_dict(strict_json(root.read(target.name).data))
        if a.retire:retire(a.store,key,expected_tip=a.expected_tip,as_of=a.as_of,reason=a.reason)
        if a.delete:delete(a.store,key,expected_tip=a.expected_tip,as_of=a.as_of)
        if a.report or a.output:
            if not a.output:raise EvidenceError('private_report_output_required')
            sha=write_report(a.output,a.store,key,as_of=a.as_of,checklist=checklist)
            print(canonical({'substantive_sha256':sha,'kind':'SIMULATED','actual_human_study':'NOT_CONDUCTED'}))
        else:print(canonical({'state':inspect(a.store,key)[2],'expected_tip':tip(a.store,key),'kind':'SIMULATED'}))
        return 1 # Limited preparation/research result, never production-ready success.
    except KeyboardInterrupt:return 130
    except (ValueError,TypeError,KeyError,IndexError,OSError,RecursionError):
        print(canonical({'error_code':'coordinator_blocked_or_invalid_no_private_details','exit_code':2}));return 2


if __name__=='__main__':raise SystemExit(main())
