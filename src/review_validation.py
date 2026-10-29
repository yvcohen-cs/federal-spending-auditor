"""Offline opt-in reviewer workflow CLI. No collector/network mode exists."""
import argparse
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, canonical, strict_json
from .review_validation_models import ReviewerDecisionInput, ReviewKind
from .review_validation_tasks import build_tasks
from .review_validation_events import append_decision, tasks_for_log
from .review_validation_study import create_study
from .review_validation_reporting import report, write_report
from .review_packet_io import outside


def main(argv=None):
    p=argparse.ArgumentParser(description='Offline review validation only; no production screening or financial authority.')
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--demo',action='store_true');mode.add_argument('--study-root');mode.add_argument('--root')
    p.add_argument('--study-dir');p.add_argument('--run-dir');p.add_argument('--packet-bundle')
    p.add_argument('--decision-log');p.add_argument('--review-kind',choices=[k.value for k in ReviewKind])
    p.add_argument('--append-input',help='Explicit schema-v1 decision input; label/time/rationale are reviewer supplied')
    a=p.parse_args(argv)
    try:
        if a.demo:
            if not a.study_dir or not a.run_dir or any((a.packet_bundle,a.decision_log,a.review_kind,a.append_input)):
                raise EvidenceError('explicit_new_synthetic_study_and_output_required')
            outside(a.run_dir,(a.study_dir,));create_study(a.study_dir)
            inputs={'study_root':a.study_dir}
        elif a.study_root:
            if not a.run_dir or any((a.study_dir,a.packet_bundle,a.decision_log,a.review_kind,a.append_input)):
                raise EvidenceError('saved_study_replay_only')
            inputs={'study_root':a.study_root}
        else:
            if a.study_dir: raise EvidenceError('root_mode_cannot_create_study')
            if a.append_input:
                if not a.decision_log or a.run_dir or a.review_kind:
                    raise EvidenceError('append_uses_explicit_input_and_new_or_existing_decision_log')
                source=Path(a.append_input).absolute()
                with EvidenceRoot(source.parent,max_bytes=65536,max_total_bytes=131072) as reader:
                    before=reader.read(source.name);value=ReviewerDecisionInput.from_dict(strict_json(before.data))
                    if reader.read(source.name,recheck=True).byte_sha256!=before.byte_sha256: raise EvidenceError('decision_input_changed')
                manifest=tasks_for_log(a.root,a.decision_log,packet_bundle=a.packet_bundle) if Path(a.decision_log).exists() else build_tasks(a.root,packet_bundle=a.packet_bundle)
                event=append_decision(a.decision_log,a.root,manifest,**{k:v for k,v in value.__dict__.items() if k!='schema_version'},
                    protected=tuple(v for v in (a.packet_bundle,a.append_input) if v))
                # Do not echo reviewer labels/rationale or private decision input.
                print(canonical({'decision_event_id':event.decision_event_id,'exit_code':0}));return 0
            if not a.run_dir: raise EvidenceError('explicit_output_required')
            inputs={'source_root':a.root,'packet_bundle':a.packet_bundle,'decision_log':a.decision_log,
                'kind':ReviewKind(a.review_kind) if a.review_kind else None}
        value=report(**inputs);sha=write_report(a.run_dir,value,**inputs)
        print(canonical({'substantive_sha256':sha,'profile':value['profile'],'human_study':'NOT_CONDUCTED','production_authorized':False,'exit_code':1}));return 1
    except KeyboardInterrupt:
        return 130
    except (ValueError,TypeError,KeyError,IndexError,OSError,RecursionError):
        print(canonical({'error_code':'invalid_review_validation_or_evidence_no_sensitive_details','exit_code':2}));return 2


if __name__=='__main__':raise SystemExit(main())
