"""Opt-in readiness assessment; collection only in the explicit holdout command."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import subprocess

from .evidence_io import EvidenceError,EvidenceRoot,canonical,strict_json
from .readiness_models import ReadinessProtocol,ReadinessAssessment
from .readiness_audit import audit_frozen,inventory
from .readiness_rules import conclusions
from .readiness_reporting import write_readiness
from .research_models import implementation_digest


def load_protocol():
    folder=Path(__file__).resolve().parent.parent/'docs'
    with EvidenceRoot(folder) as root: return ReadinessProtocol.from_dict(strict_json(root.read('readiness-protocol-v1.json').data))


def assess(root,*,holdout=None,protocol=None,executed_at_utc=None):
    protocol=protocol or load_protocol();fingerprint=implementation_digest()
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parent.parent,text=True,timeout=5).strip()
    frozen=audit_frozen(root,protocol);cohorts=(frozen,)
    if holdout is not None:
        from .readiness_holdout import audit_holdout
        excluded=[s.selected_native_id for s in frozen.slots if s.selected_native_id is not None]
        cohorts+=(audit_holdout(holdout,protocol,excluded),)
    dimensions,hard,modes=conclusions(cohorts)
    result=ReadinessAssessment(protocol=protocol,implementation_commit=commit,implementation_sha256=fingerprint,
        cohorts=cohorts,dimensions=dimensions,hard_gates=hard,modes=modes,executed_at_utc=executed_at_utc)
    if implementation_digest()!=fingerprint: raise EvidenceError('readiness_implementation_changed')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description='Evidence readiness only; no automatic scale authorization.')
    p.add_argument('--root',required=True);p.add_argument('--run-dir',required=True);p.add_argument('--holdout-root')
    p.add_argument('--live',action='store_true');p.add_argument('--execution-time',action='store_true')
    args=p.parse_args(argv)
    try:
        protocol=load_protocol()
        if args.live:
            if args.holdout_root or args.execution_time: raise EvidenceError('live_holdout_is_separate_from_readiness_output')
            # Verify the frozen exclusion cohort before making any requests.
            original=audit_frozen(args.root,protocol)
            if not original.available or not original.unchanged: raise EvidenceError('verified_frozen_exclusion_cohort_required')
            from .readiness_holdout import collect_holdout
            from .review_packet_io import outside
            collect_holdout(outside(args.run_dir,(args.root,)),protocol,[s.selected_native_id for s in original.slots],live=True)
            print(canonical({'holdout_preserved':True,'maximum_http_requests':protocol.holdout_http_limit,'exit_code':1}));return 1
        result=assess(args.root,holdout=args.holdout_root,protocol=protocol,
            executed_at_utc=datetime.now(timezone.utc).isoformat() if args.execution_time else None)
        value=write_readiness(args.run_dir,result,protected=(args.root,)+((args.holdout_root,) if args.holdout_root else ()))
        print(canonical({'substantive_sha256':value,'modes':[{ 'mode':m.mode,'result':m.result.value} for m in result.modes],'exit_code':1}));return 1
    except KeyboardInterrupt: return 130
    except (ValueError,TypeError,KeyError,IndexError,OSError,subprocess.SubprocessError):
        print(canonical({'error_code':'readiness_evaluation_failed','exit_code':2}));return 2


if __name__=='__main__': raise SystemExit(main())
