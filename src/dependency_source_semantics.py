"""C21 official-document attempts; unavailable text is never inferred from search."""
from .evidence import _timestamp
from .evidence_io import EvidenceRoot,EvidenceError,digest,strict_json
from .source_reference_semantics import visible_projection

DOCUMENTS={
 'fpds-v14-dictionary':('fpds','https://www.fpds.gov/downloads/FPDSNG_DataDictionary_V14_OT.pdf',None,None),
 'dod-2016-guidance':('dod','https://www.acq.osd.mil/dpap/dars/pgi/pgi_htm/r20161021/PGI204_6.htm',None,None),
 'sam-guide':('samgov','https://open.gsa.gov/api/contract-awards/','033a7007b702d25f1582f06feb8c0dd5d6dce3afee056cb57b61995e0e7443c7','contractId.referencedIDVModificationNumber'),
 'usa-transactions':('usaspending','https://raw.githubusercontent.com/fedspendingtransparency/usaspending-api/c2b82690eb044e130afc80b546343a2af0b4af1a/usaspending_api/api_contracts/contracts/v2/transactions.md','76a50f3445670d8ee5488770d6583a7f6399a093a903dabfbab77344f1eba078','hasNext'),
}

def documentation(path):
 out=[]
 with EvidenceRoot(path,max_bytes=2*1048576,max_total_bytes=12*1048576) as root:
  for name,(source,url,known,quote) in DOCUMENTS.items():
   ms=root.read(name+'.json');m=strict_json(ms.data);body=root.read(name+'.body')
   if (type(m) is not dict or set(m)!={'schema_version','request','status','retrieved_at_utc','body_complete','body_sha256','representation','location','content_type'}
       or type(m['schema_version']) is not int or m['schema_version']!=1
       or type(m['status']) is not int or not 100<=m['status']<=599 or type(m['body_complete']) is not bool
       or m['request']!={'method':'GET','url':url,'redirects':False}
       or m['representation']!='HTTP_entity_bytes_after_content_decoding' or m['body_sha256']!=body.byte_sha256
       or type(m['retrieved_at_utc']) is not str):raise EvidenceError('C21_document_provenance_conflict')
   _timestamp(m['retrieved_at_utc']);available=m['status']==200 and m['body_complete'] and m['location'] is None
   reviewed=available and known is not None and known==body.byte_sha256
   text,encoding,basis=visible_projection(body.data,m['content_type']) if reviewed else ('',None,None)
   start=text.find(quote) if reviewed else -1
   out.append({'source':source,'name':name,'metadata':m,'metadata_sha256':ms.byte_sha256,
     'body_file':name+'.body','metadata_file':name+'.json',
     'state':'UNAVAILABLE_OR_INCOMPLETE' if not available else 'REVIEWED_CLAUSE_OBSERVED' if start>=0 else 'UNREVIEWED_DOCUMENT_VERSION',
     'clause':quote if start>=0 else None,'visible_character_span':[start,start+len(quote)] if start>=0 else None,
     'projection_encoding':encoding,'encoding_basis':basis,'publisher_version':None,
     'historical_applicability_rule_established':False,'directed_correction_supported':False,
     'source_wide_completeness_supported':False,'redirect_followed':False})
   if root.read(name+'.json',recheck=True).byte_sha256!=ms.byte_sha256 or root.read(name+'.body',recheck=True).byte_sha256!=body.byte_sha256:raise EvidenceError('C21_document_changed')
 return out
