"""Opt-in Phase 4C3 CLI. Existing C2 collection contract remains unchanged."""
import argparse
from pathlib import Path

from .evidence_io import EvidenceError, canonical
from .sam_semantics_reporting import report, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only SAM pagination, identity and historical evidence research; no financial arithmetic.')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--offline', action='store_true')
    mode.add_argument('--demo', action='store_true')
    mode.add_argument('--root', action='append', help='Existing C2 capture; repeat up to three same-profile captures')
    mode.add_argument('--live', action='store_true')
    parser.add_argument('--selection'); parser.add_argument('--capture-dir')
    parser.add_argument('--run-dir', required=True)
    args = parser.parse_args(argv)
    try:
        from .review_packet_io import outside
        captures = (); access = 'not_checked_offline_no_credential_read'
        if args.offline:
            if args.selection or args.capture_dir:
                raise EvidenceError('offline_does_not_collect')
            import os
            access = 'configured_material_present_not_authenticated' if bool(os.environ.get('SAM_GOV_API_KEY')) else 'unavailable_no_configured_credential'
        elif args.root:
            if args.selection or args.capture_dir:
                raise EvidenceError('replay_does_not_collect')
            captures = tuple(args.root)
            if len(captures)>3:
                raise EvidenceError('three_capture_limit')
            outside(args.run_dir, captures)
        elif args.demo:
            if args.selection or args.capture_dir:
                raise EvidenceError('demo_has_fixed_synthetic_selection')
            from .sam_validation import demo
            capture = Path(args.run_dir).with_name(Path(args.run_dir).name+'-synthetic-evidence')
            outside(args.run_dir, (capture,))
            demo(capture); captures = (capture,)
        else:
            if not args.selection or not args.capture_dir:
                raise EvidenceError('explicit_frozen_selection_and_capture_required')
            from .collect_evidence import load_input
            from .sam_validation_capture import SAMResearchSelection, collect
            selection = SAMResearchSelection.from_dict(load_input(args.selection))
            if selection.profile!='live':
                raise EvidenceError('live_profile_required')
            outside(args.capture_dir, (args.selection,)); outside(args.run_dir, (args.selection, args.capture_dir))
            # No pagination change, alternative route or automatic resume.
            collect(args.capture_dir, selection, live=True)
            captures = (args.capture_dir,)
        value = report(captures, access=access)
        sha = write_report(args.run_dir, value, captures=captures)
        print(canonical({'substantive_sha256': sha, 'profile': value['profile'], 'migration': value['migration_recommendation'], 'exit_code': 1}))
        return 1
    except KeyboardInterrupt:
        return 130
    except (ValueError, TypeError, KeyError, IndexError, OSError):
        print(canonical({'error_code': 'sam_semantics_blocked_or_invalid_no_sensitive_details', 'exit_code': 2}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
