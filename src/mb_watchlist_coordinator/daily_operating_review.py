"""Build a public operating candidate from published inputs; no activation."""
from dataclasses import asdict
from pathlib import Path

from .authenticated_startup import AuthStartupSettings
from .controller_bootstrap import _proposal
from .daily_collector import DailyCollectorSettings
from .daily_session import DailySettings, DailySession, OWNER, regular_path
from .daily_supervision import DailyWorkerConfiguration,read_json
from .integrated_catalog import DirectoryCatalog
from .operating_plan import proposed_policy
from .daily_admission import DailyAdmissionPolicy as AdmissionPolicy
from .sampling_policy import SamplingPolicy
from .sampling_projection import SamplingMembership
from .sampling_request_store import SamplingRequestStore
from .sampling_service import SamplingPublicationService, PublicationSettings
from .sampling_journal import SamplingJournal
from .sampling_requests import digest, plain, timestamp


def build_operating_review(opening,focus,*,journal,catalog,state_root,ecfg,clock=None):
    from mb_market_data.daily_journal import DailyQuoteObservationStore as QuoteObservationStore
    settings=DailySettings(str(regular_path(state_root)),str(regular_path(journal,exists=True)),
        str(regular_path(opening,exists=True)),str(regular_path(focus,exists=True)),digest(proposed_policy()))
    directory=DirectoryCatalog.load(regular_path(catalog))
    session=DailySession(settings,directory,clock=clock) # describes only; no attach/initialize
    if session.claim_path.exists():
        if (read_json(session.claim_path)!=session.claim or read_json(session.root/'session.json')!=
                {'claim':session.claim,'binding':session.binding,'status':'ATTACHED'}):
            raise ValueError('Review cannot replace an existing daily attachment binding')
    proposal,_=_proposal(settings.focus_proposal)
    policy=session.binding['policy']
    requests=SamplingRequestStore(Path(settings.state_root)/'requests.sqlite3',
        session_date=proposal.session_date,baseline=SamplingMembership(
            frozenset(proposal.uni_symbols),frozenset(proposal.focus_symbols),frozenset()),
        policy=SamplingPolicy(policy['operator_actor_id'],**policy['stabilization']),
        admission=AdmissionPolicy(directory.catalog_id,frozenset(directory.symbols),frozenset({OWNER}),1,'session'))
    store=QuoteObservationStore(settings.journal_path,session_date=proposal.session_date,schema_version=2)
    service=SamplingPublicationService(Path(settings.state_root)/'publication.sqlite3',
        request_store=requests,journal=SamplingJournal(store),settings=PublicationSettings('daily-hot-publication',1,.5,
            timestamp(session.binding['stop_at_utc'])))
    configuration=DailyWorkerConfiguration(settings,str(directory.path),
        DailyCollectorSettings(settings.journal_path,plain(service.identity),plain(session.binding),plain(session.claim),
            session.binding['start_at_utc'],session.binding['stop_at_utc'],9360,1),
        AuthStartupSettings(str(regular_path(ecfg)),session.binding['stop_at_utc']))
    raw=configuration.payload()
    content={'contract':'daily-hot-operating-review-v1','session_date':session.binding['session_date'],
        'configuration':raw,'configuration_sha256':digest(raw),'policy_sha256':digest(policy),
        'status':'REVIEW_CANDIDATE','activation_allowed':False,'proposed_values_adopted':False,
        'actual_vault_access':False,'provider_access':False,'production_changes':False,
        'opening_counts':{'uni':len(proposal.uni_symbols),'focus':len(proposal.focus_symbols),'hot':0},
        'regular_close_utc':session.binding['stop_at_utc'],
        'unmanaged_channels':['uni','focus','health'],
        'existing_driver_state':(Path(settings.state_root)/'driver-state.json').exists(),
        'required_before_activation':['Windows operating qualification','Representative full-day/provider capacity',
            'Deployment/rollback review and explicit settings/activation approval']}
    return dict(content,review_sha256=digest(content))
