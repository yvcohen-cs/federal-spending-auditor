"""Opt-in SAM research harness: explicit live, synthetic demo, or offline audit."""
import argparse
from pathlib import Path

from .evidence_io import EvidenceError, canonical, digest, strict_json
from .sam_validation_capture import SAMResearchSelection, collect
from .sam_validation_reporting import report, write_report
from .scope_models import ScopeRequest


def synthetic_selection(rule='synthetic_row_offset'):
    return SAMResearchSelection(subjects=(ScopeRequest(piid='SYNTH-SAM-0001.A',agency='0001',parent_piid='SYNTH-IDV-0001',parent_agency='0002',namespace='samgov-v1'),),
        pagination_rule=rule,profile='synthetic',limit=2)


def synthetic_row(mod='P00001'):
    return {'contractId':{'piid':'SYNTH-SAM-0001.A','subtier':{'code':'0001'},'referencedIDVPiid':'SYNTH-IDV-0001',
        'referencedIDVSubtier':{'code':'0002'},'modificationNumber':mod,'transactionNumber':'0'},
        'coreData':{'coreVersionId':'1.5','awardOrIDV':'AWARD','awardOrIDVType':{'code':'C'}},
        'awardDetails':{'dollars':{'actionObligation':'-12.00'},'totalContractDollars':{'totalActionObligation':'100.00'},
            'dates':{'dateSigned':'2024-10-01','periodOfPerformanceStartDate':'2024-11-01'},
            'transactionData':{'status':{'code':'F','name':'FINAL'},'version':'1.5','createdDate':'2024-10-01T09:00:00',
                'lastModifiedDate':'2025-01-01T10:00:00Z'}}}


def demo(path):
    selected=synthetic_selection()
    def transport(request,sequence):
        rows=[synthetic_row('0'),synthetic_row()] if sequence==0 else [synthetic_row('P00002')]
        body={'awardSummary':rows,'totalRecords':'3','limit':'2','offset':str(request['parameters']['offset'])}
        return {'status':200,'retrieved_at_utc':f'2025-01-0{sequence+1}T00:00:00Z','body_complete':True,'error_code':None,
            'headers':{'content-type':'application/json','etag':'synthetic-entity-tag'}},canonical(body).encode()
    collect(path,selected,live=True,fixture_transport=transport,sleep=lambda _:None)
    return report(path,access='synthetic_no_credential_used')


def main(argv=None):
    p=argparse.ArgumentParser(description='SAM validation research only; no production migration or financial integration.')
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--live',action='store_true');mode.add_argument('--demo',action='store_true');mode.add_argument('--root');mode.add_argument('--offline',action='store_true')
    p.add_argument('--selection');p.add_argument('--capture-dir');p.add_argument('--run-dir',required=True)
    a=p.parse_args(argv)
    try:
        from .review_packet_io import outside
        capture=None
        if a.live:
            if not a.selection or not a.capture_dir: raise EvidenceError('explicit_SAM_selection_and_capture_directory_required')
            from .collect_evidence import load_input
            selected=SAMResearchSelection.from_dict(load_input(a.selection))
            if selected.profile!='live': raise EvidenceError('live_profile_required')
            outside(a.capture_dir,(a.selection,));outside(a.run_dir,(a.capture_dir,a.selection))
            capture=a.capture_dir
            collect(a.capture_dir,selected,live=True)
            value=report(a.capture_dir,access='configured_credential_used_entitlement_not_certified')
            protected=(a.capture_dir,a.selection)
        elif a.demo:
            if a.selection or a.capture_dir: raise EvidenceError('demo_has_fixed_synthetic_selection')
            capture=Path(a.run_dir).with_name(Path(a.run_dir).name+'-synthetic-evidence')
            value=demo(capture);protected=(capture,)
        elif a.root:
            if a.selection or a.capture_dir: raise EvidenceError('offline_replay_cannot_collect')
            outside(a.run_dir,(a.root,));capture=a.root;value=report(a.root,access='offline_capture_replay_no_credential_read');protected=(a.root,)
        else:
            if a.selection or a.capture_dir: raise EvidenceError('offline_no_capture_inputs_required')
            import os
            availability='configured_material_present_not_authenticated' if bool(os.environ.get('SAM_GOV_API_KEY')) else 'unavailable_no_configured_credential'
            value=report(access=availability);protected=()
        sha=write_report(a.run_dir,value,protected=protected,capture=capture)
        print(canonical({'substantive_sha256':sha,'profile':value['profile'],'migration':value['migration_recommendation'],'exit_code':1}));return 1
    except KeyboardInterrupt: return 130
    except EvidenceError as exc:
        print(canonical({'error_code':exc.code,'exit_code':2}));return 2
    except (ValueError,TypeError,KeyError,IndexError,OSError):
        print(canonical({'error_code':'sam_validation_blocked_or_invalid_no_sensitive_details','exit_code':2}));return 2


if __name__=='__main__': raise SystemExit(main())
