"""Preserve published opening history for the unchanged, isolated p75 trial.

Export is a separate, read-only operator action on opening membership tables.
Preparation consumes that closed export and the failed attempt's cached inputs;
it never opens the production journal, requests a directory, or starts a role.
"""
from contextlib import closing
from datetime import date, datetime, timezone
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
PACKET_SHA = '8f6af02c93746adfb80b1b3e2ca80bf7543de96ac0039bd581a46859e743c5c1'
CONTRACT = 'closed-opening-membership-export-v1'
QUALIFICATION = 'opening-baseline-copy-offline-qualification-v1'
TABLES = ('sampling_membership_revision', 'sampling_channel_revision', 'sampling_channel_member')
ORDERS = ('revision', 'revision,channel', 'revision,channel,ordinal')
CHECKS = 12


def configure(packet):
    packet = Path(packet).resolve()
    sys.path[:0] = [str(packet/'coordinator/src'), str(packet/'market_data/src'), str(packet/'coordinator/tests')]
    from mb_watchlist_coordinator.live_profile import source_guard
    if source_guard(packet) != PACKET_SHA:
        raise ValueError('The original qualified p75 source inventory is required')
    return packet


def own_inventory():
    from mb_watchlist_coordinator.live_profile import source_guard
    return source_guard(ROOT)


def _write_new(path, value):
    from mb_watchlist_coordinator.daily_supervision import sealed
    raw = (json.dumps(sealed(value), indent=2, sort_keys=True)+'\n').encode()
    with Path(path).open('xb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())


def _rows(connection):
    return {table:[dict(row) for row in connection.execute('SELECT * FROM '+table+' ORDER BY '+order)]
            for table,order in zip(TABLES,ORDERS)}


def _insert_rows(connection, tables):
    if set(tables) != set(TABLES):
        raise ValueError('Only the three opening membership tables may be imported')
    for table in TABLES:
        columns = [r[1] for r in connection.execute('PRAGMA table_info('+table+')')]
        records = tables[table]
        if not isinstance(records,list) or any(not isinstance(r,dict) or set(r)!=set(columns) for r in records):
            raise ValueError('Opening table columns differ from the pinned native schema')
        # Identifiers come from the pinned native schema, never the input file.
        sql = 'INSERT INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')'
        connection.executemany(sql, [tuple(r[k] for k in columns) for r in records])


def _validated_rows(tables, proposals, *, observed):
    from mb_market_data.quote_observation_store import QuoteObservationStore, _SCHEMA_V2_SQL
    from mb_market_data.sampling_membership import assess_revision_candidate
    if (len(tables.get(TABLES[0],[]))!=2 or len(tables.get(TABLES[1],[]))!=6
            or len(tables.get(TABLES[2],[]))!=sum(len(p.uni_symbols)+len(p.focus_symbols) for p in proposals)):
        raise ValueError('Exactly the published r0/r1 opening membership is required')
    with closing(sqlite3.connect(':memory:')) as c:
        c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); c.executescript(_SCHEMA_V2_SQL)
        _insert_rows(c,tables)
        reader=QuoteObservationStore(':memory:',session_date=proposals[0].session_date,schema_version=2)
        rows=c.execute('SELECT * FROM sampling_membership_revision ORDER BY revision').fetchall()
        revisions=tuple(reader._membership_revision_from_row(c,row) for row in rows)
        if [p.content_sha256 for p in revisions]!=[p.content_sha256 for p in proposals]:
            raise ValueError('Published opening content differs from the retained proposals')
        previous=None
        for revision in revisions:
            assess_revision_candidate(previous,revision)
            if revision.published_at>observed or previous and revision.published_at<previous.published_at:
                raise ValueError('Original publication time is inconsistent with the export')
            for channel in ('uni','focus','hot'):
                ordinals=[r[0] for r in c.execute('SELECT ordinal FROM sampling_channel_member '
                    'WHERE revision=? AND channel=? ORDER BY ordinal',(revision.revision,channel))]
                if ordinals!=list(range(len(ordinals))):
                    raise ValueError('Opening membership ordinals are not contiguous')
            previous=revision
    return revisions


def retained_inputs(packet, failed, *, clock=None):
    from mb_watchlist_coordinator import market_open_check as check
    from mb_watchlist_coordinator.controller_bootstrap import _proposal
    from mb_watchlist_coordinator.integrated_catalog import DirectoryCatalog
    from mb_watchlist_coordinator.sampling_requests import timestamp
    packet=configure(packet); now=(clock or (lambda:datetime.now(timezone.utc)))()
    day=check.market_window(now); _,failed=check._root(packet,failed,exists=True)
    if (not failed.name.startswith('market_open_daily_'+day.strftime('%Y%m%d')+'_')
            or any((failed/name).exists() for name in ('prepared.json','approved-trial-review.json',
                                                       'candidate-review.json','daily_hot_check','daily_outer_check'))):
        raise ValueError('Only the retained, unprepared after-opening attempt may supply cached inputs')
    opening,focus=failed/'inputs/opening-r0.json',failed/'inputs/focus-r1.json'
    p0,h0=_proposal(opening); p1,h1=_proposal(focus)
    start=now.astimezone(check.ET).replace(hour=9,minute=30,second=0,microsecond=0)
    if (p0.session_date!=day or p1.session_date!=day or p0.revision!=0 or p1.revision!=1
            or p0.effective_at!=start or p1.effective_at!=start or p0.uni_symbols!=p1.uni_symbols
            or p0.focus_symbols or p0.hot_symbols or p1.hot_symbols or not 1<=len(p1.focus_symbols)<=40):
        raise ValueError('Retained current-day opening/Focus proposals differ')
    journal=failed/f'quote_observation_journal_v2_api_opening_{day}'/f'{day}.sqlite3'
    if not journal.is_file() or journal.is_symlink():
        raise ValueError('Retained partial journal is missing')
    with closing(sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
        c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
        if any(c.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in
               (*TABLES,'poll_run','poll_slot_skip','quote_acquisition','quote_observation')):
            raise ValueError('The retained attempt contains recorded history; preserve it without reuse')
    catalog=DirectoryCatalog.load(failed/'daily_catalog')
    if any(timestamp(s['retrieved_at_utc']).astimezone(check.ET).date()!=day
           or timestamp(s['retrieved_at_utc'])>now for s in catalog.public['sources'].values()):
        raise ValueError('The retained directory is not from this ET session')
    return {'packet':packet,'failed':failed,'day':day,'now':now,'proposals':(p0,p1),
            'paths':(opening,focus),'hashes':(h0,h1),'catalog':catalog}


def export_baseline(packet, failed, journal, output, *, clock=None):
    """Read only identity and membership; never initialize or write the source."""
    from mb_watchlist_coordinator.sampling_requests import utc_text
    context=retained_inputs(packet,failed,clock=clock); day=context['day']; journal=Path(journal); output=Path(output)
    if (not journal.is_absolute() or journal!=journal.resolve() or not journal.is_file() or journal.is_symlink()
            or journal.name!=f'{day}.sqlite3'
            or journal.parent.name!=f'quote_observation_journal_v2_api_opening_{day}'
            or journal.is_relative_to(context['packet']) or output.exists()
            or not output.is_absolute() or output!=output.resolve() or not output.parent.is_dir()
            or output.is_relative_to(journal.parent) or output.is_relative_to(context['packet'])):
        raise ValueError('An existing external daily journal and a new export path are required')
    with closing(sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
        c.row_factory=sqlite3.Row; c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
        identity=dict(c.execute('SELECT * FROM store_identity WHERE singleton=1').fetchone())
        if (c.execute('PRAGMA user_version').fetchone()[0]!=2 or identity['schema_version']!=2
                or identity['session_date']!=str(day) or identity['membership_contract']!='nested-uni-focus-hot-v1'):
            raise ValueError('Published source schema/date/contract differ')
        tables=_rows(c)
    _validated_rows(tables,context['proposals'],observed=context['now'])
    value={'contract':CONTRACT,'session_date':str(day),'exported_at_utc':utc_text(context['now']),
        'packet_inventory_sha256':PACKET_SHA,'source_journal_path':str(journal),'source_identity':identity,
        'proposal_file_sha256':list(context['hashes']),
        'published_anchor':[p.content_sha256 for p in context['proposals']],
        'source_access':'read-only SQLite transaction; identity and membership tables only',
        'quote_or_acquisition_content_read':False,'source_database_written':False,'tables':tables}
    _write_new(output,value)
    return value


def prepare_from_export(packet, failed, export, *, clock=None):
    """Import existing history into a fresh isolated journal, not new publication."""
    from mb_market_data.daily_journal import DailyQuoteObservationStore
    from mb_market_data.quote_observation_store import PollRunProvenance
    from mb_market_data.polling_cadence import CADENCE_PROFILES
    from mb_market_data.quote_journal_audit import audit_quote_journal
    from mb_watchlist_coordinator import market_open_check as check
    from mb_watchlist_coordinator.controller_bootstrap import strict_json
    from mb_watchlist_coordinator.daily_supervision import unseal
    from mb_watchlist_coordinator.sampling_requests import digest,timestamp,utc_text
    context=retained_inputs(packet,failed,clock=clock); day=context['day']; now=context['now']
    export=Path(export)
    if not export.is_absolute() or not export.is_file() or export.is_symlink() or export.stat().st_size>16_000_000:
        raise ValueError('A bounded closed opening export is required')
    raw=export.read_bytes(); value=unseal(strict_json(raw.decode('utf-8')))
    if (set(value)!={'contract','session_date','exported_at_utc','packet_inventory_sha256','source_journal_path',
            'source_identity','proposal_file_sha256','published_anchor','source_access',
            'quote_or_acquisition_content_read','source_database_written','tables'}
            or value['contract']!=CONTRACT or value['session_date']!=str(day)
            or timestamp(value['exported_at_utc'])>now
            or timestamp(value['exported_at_utc']).astimezone(check.ET).date()!=day
            or value['packet_inventory_sha256']!=PACKET_SHA
            or value['proposal_file_sha256']!=list(context['hashes'])
            or value['published_anchor']!=[p.content_sha256 for p in context['proposals']]
            or value['quote_or_acquisition_content_read'] is not False or value['source_database_written'] is not False
            or value['source_identity']['schema_version']!=2
            or value['source_identity']['session_date']!=str(day)
            or value['source_identity']['membership_contract']!='nested-uni-focus-hot-v1'
            or timestamp(value['source_identity']['created_at_utc'])>timestamp(value['exported_at_utc'])):
        raise ValueError('Closed baseline export does not match the retained inputs')
    revisions=_validated_rows(value['tables'],context['proposals'],observed=timestamp(value['exported_at_utc']))
    root=context['packet']/'runs'/('market_open_daily_'+day.strftime('%Y%m%d')+'_'+uuid4().hex[:8])
    check._root(context['packet'],root); root.mkdir(exist_ok=False)
    inputs=root/'inputs'; inputs.mkdir()
    for old,name in zip(context['paths'],('opening-r0.json','focus-r1.json')):
        data=old.read_bytes()
        if hashlib.sha256(data).hexdigest()!=context['hashes'][('opening-r0.json','focus-r1.json').index(name)]:
            raise ValueError('Retained proposal changed during preparation')
        with (inputs/name).open('xb') as out:out.write(data)
    (root/'opening-baseline-export.json').write_bytes(raw)
    saved=context['catalog'].persist(root/'daily_catalog')
    journal=root/f'quote_observation_journal_v2_api_opening_{day}'/f'{day}.sqlite3'
    store=DailyQuoteObservationStore(journal,session_date=day,schema_version=2); store.initialize()
    # A historical copy retains all original publication times. No call to
    # record_membership_revision and no live clock override occurs here.
    with closing(sqlite3.connect(journal)) as c:
        c.execute('PRAGMA foreign_keys=ON')
        with c:
            c.execute('BEGIN IMMEDIATE'); _insert_rows(c,value['tables'])
    copied=store.membership_revisions_in_effective_order()
    if [(r.content_sha256,r.published_at) for r in copied]!=[(r.content_sha256,r.published_at) for r in revisions]:
        raise ValueError('Native parser did not preserve the exported opening history')
    for channel,seconds in CADENCE_PROFILES['interleaved-v1'].items():
        store.record_run(PollRunProvenance('context-'+channel,now,'market-open-check-baseline',
            {'watchlist_kind':channel,'poll_seconds':list(seconds),'cadence_profile':'interleaved-v1',
             'context_only':True,'quote_collection_performed':False}))
    if not audit_quote_journal(journal).passed:
        raise ValueError('Native isolated baseline audit failed')
    prepared={'contract':check.CONTRACT,'source_root':str(context['packet']),'root':str(root),
        'source_inventory_sha256':PACKET_SHA,'session_date':str(day),'prepared_at_utc':utc_text(now),
        'original_inputs':{key:{'path':str(path),'file_sha256':sha}
            for key,path,sha in zip(('opening','focus'),context['paths'],context['hashes'])},
        'copied_inputs':{'opening':str(inputs/'opening-r0.json'),'focus':str(inputs/'focus-r1.json')},
        'published_anchor':value['published_anchor'],'catalog_path':str(saved.path),
        'catalog_sha256':digest(saved.public),'journal_path':str(journal),'limits':dict(check.LIMITS),
        'production_journal_access':False,
        'baseline_import':{'contract':CONTRACT,'closed_export_path':str(root/'opening-baseline-export.json'),
            'closed_export_file_sha256':hashlib.sha256(raw).hexdigest(),
            'exported_at_utc':value['exported_at_utc'],'imported_at_utc':utc_text(now),
            'original_published_at_utc':[utc_text(r.published_at) for r in revisions],
            'retained_failed_root':str(context['failed']),'new_directory_downloads':0,
            'source_read_scope':'separate operator export; trial preparation and roles consume isolated files'}}
    _write_new(root/'prepared.json',prepared)
    if check.load_prepared(str(context['packet']),str(root))!=prepared:
        raise ValueError('The unchanged trial loader rejected the imported baseline')
    return prepared


def _qualified(folder,contract,inventory,count,*,windows=True):
    for path in (Path(folder)/'runs').glob('*/verification.json'):
        try:
            v=json.loads(path.read_text())
            if (v['contract']==contract and v['result']=='PASS' and v['tests']==v['passed']==count
                    and not any(v[k] for k in ('failures','errors','skipped'))
                    and (not windows or v['windows_checks_passed'] is True)
                    and v['source_inventory_sha256']==inventory):return True
        except (OSError,ValueError,TypeError,KeyError):pass
    return False


def verify(packet,inventory):
    def denied(*a,**k):raise OSError('Network denied during opening-baseline qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    spec=importlib.util.spec_from_file_location('_baseline_copy_tests',ROOT/'test_baseline_fix.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.PACKET=packet; module.HELPER=sys.modules[__name__]
    suite=unittest.defaultTestLoader.loadTestsFromModule(module)
    if suite.countTestCases()!=CHECKS:raise ValueError('Focused baseline check count differs')
    folder=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8]);folder.mkdir(parents=True)
    module.PROOF_ROOT=folder/'proof'
    print('OFFLINE opening-history copy: synthetic journals, actual SQLite read-only connections. No API, password or production access.',flush=True)
    began=time.monotonic()
    with (folder/'tests.log').open('w',encoding='utf-8') as log:
        class Output:
            def write(self,v):log.write(v);sys.stdout.write(v)
            def flush(self):log.flush();sys.stdout.flush()
        result=unittest.TextTestRunner(stream=Output(),verbosity=2).run(suite)
    proof_path=module.PROOF_ROOT/'after-opening-proof.json'
    proof=json.loads(proof_path.read_text()) if proof_path.exists() else None
    passed=bool(result.wasSuccessful() and result.testsRun==CHECKS and not result.skipped
        and proof and proof['native_audit_passed'] and proof['original_publication_times_preserved']
        and proof['unchanged_original_loader_accepted'] and proof['new_membership_publication_calls']==0)
    report={'contract':QUALIFICATION,'result':'PASS' if passed else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[t.id() for t,_ in result.failures+result.errors],'seconds':time.monotonic()-began,
        'source_inventory_sha256':inventory,'original_packet_inventory_sha256':PACKET_SHA,
        'platform':sys.platform,'python':list(sys.version_info[:3]),
        'windows_checks_passed':passed and os.name=='nt','network':'denied','production_access':False,
        'actual_vault_access':False,'actual_provider_used':False,'original_packet_source_changed':False,
        'no_live_clock_override':True,'new_directory_downloads':0,'production_hot_enabled':False,
        'prior_windows75_repeated':False,'live_trial_executed':False,'native_baseline_proof':proof}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    configure(packet);own_inventory()
    print(json.dumps(report,indent=2),flush=True);print('Saved report:',folder/'verification.json',flush=True)
    return 0 if passed else 1


def main(argv):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    for name in ('verify','export','prepare'):
        sub=commands.add_parser(name);sub.add_argument('--packet-root',required=True)
        if name!='verify':sub.add_argument('--failed-trial-root',required=True)
        if name=='export':sub.add_argument('--journal',required=True);sub.add_argument('--output',required=True)
        if name=='prepare':sub.add_argument('--baseline-export',required=True)
    args=parser.parse_args(argv);packet=configure(args.packet_root);inventory=own_inventory()
    if args.command=='verify':return verify(packet,inventory)
    if not _qualified(ROOT,QUALIFICATION,inventory,CHECKS):
        raise ValueError('First pass the 12-check Windows78 baseline-copy verifier')
    if not _qualified(packet,'market-open-daily-path-offline-qualification-v1',PACKET_SHA,48):
        raise ValueError('The original matching Windows75 qualification is required; no repeat is requested')
    if args.command=='export':
        result=export_baseline(packet,args.failed_trial_root,args.journal,args.output)
        print(json.dumps({'contract':result['contract'],'exported_at_utc':result['exported_at_utc'],
            'published_anchor':result['published_anchor'],'source_access':result['source_access'],
            'quote_or_acquisition_content_read':False,'source_database_written':False},indent=2),flush=True)
        print('Saved opening baseline:',Path(args.output),flush=True)
    else:
        result=prepare_from_export(packet,args.failed_trial_root,args.baseline_export)
        print(json.dumps(result,indent=2),flush=True);print('Prepared trial:',result['root'],flush=True)
        print('Original p75 sources, original failed preparation and original publication times preserved. No password or provider action.',flush=True)
    return 0


if __name__=='__main__':
    sys.dont_write_bytecode=True
    try:raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:raise SystemExit(130)
    except Exception as error:
        print('Opening baseline correction refused:',str(error) if type(error) is ValueError else type(error).__name__,flush=True)
        print('Keep all original and newly created evidence. No reset or automatic provider retry.',flush=True)
        raise SystemExit(70)
