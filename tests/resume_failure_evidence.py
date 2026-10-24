"""Allowlisted synthetic manual-controller diagnostics before test cleanup."""
import json
import re

from runtime_process_evidence import FailureEvidenceResult

STAGES=frozenset(('resume_reserved','credentials_accepted','previous_roles_quiescent',
    'saved_native_work_recovered','runtime_reopened'))
EXCEPTIONS=frozenset(('ValueError','TypeError','KeyError','OSError','FileNotFoundError',
    'ServiceBusy','AcquisitionBusy','ResumeError','StartupError','RuntimeError','GeneratorExit'))


def safe_trace(path):
    if not path.is_file():return []
    rows=[]
    for line in path.read_text().splitlines():
        value=json.loads(line);event=value.get('event')
        if event=='stage':
            rows.append({'event':event,'stage':value['stage'] if value.get('stage') in STAGES else 'unrecognized'})
        elif event=='fixed_exception':
            name=value.get('function','')
            rows.append({'event':event,'function':name if re.fullmatch('[A-Za-z_][A-Za-z_0-9]{0,60}|<genexpr>',name) else 'unrecognized',
                'line':value.get('line') if type(value.get('line')) is int else None,
                'exception_type':value.get('exception_type') if value.get('exception_type') in EXCEPTIONS else 'unrecognized'})
        elif event in ('resume_client_constructed','resume_client_closed','identity_quote','controller_ready','native_goal'):
            rows.append({'event':event})
    return rows[-40:]


class ManualFailureEvidenceResult(FailureEvidenceResult):
    def _capture(self,test):
        before=len(self.evidence_files);super()._capture(test)
        if len(self.evidence_files)==before or not hasattr(test,'controller_log'):return
        try:
            path=self.evidence_root/self.evidence_files[-1]
            value=json.loads(path.read_text());value['manual_controller_trace']=safe_trace(test.controller_log)
            path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
        except Exception:self.evidence_write_errors+=1
