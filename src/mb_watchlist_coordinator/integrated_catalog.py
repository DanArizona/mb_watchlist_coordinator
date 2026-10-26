"""Bounded exact-symbol directory input for the isolated controller.

No daily screening or broker identity is inferred from directory membership.
Network retrieval is opt-in, uses at most two owned children, and is never
retried. This API does not initialize a journal or accept credentials.
"""
import base64
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

from .sampling_requests import canonical, digest, freeze, plain, timestamp, utc_text

SOURCES = {
    'nasdaq': 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt',
    'other': 'https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt',
}
MAX_BYTES = 4_000_000
ET = ZoneInfo('America/New_York')


class CatalogError(ValueError):
    def __init__(self, code, receipts=()):
        self.code, self.receipts = code, freeze(list(receipts))
        super().__init__(code)


def _rows(raw, label, at):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise CatalogError('catalog_body_invalid')
    try:
        rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig')), delimiter='|'))
        fields = rows.pop(0)
        required = ({'Symbol', 'Security Name', 'Market Category', 'Test Issue',
                     'Financial Status', 'Round Lot Size', 'ETF'} if label == 'nasdaq' else
                    {'ACT Symbol', 'Security Name', 'Exchange', 'CQS Symbol', 'ETF',
                     'Round Lot Size', 'Test Issue', 'NASDAQ Symbol'})
        if len(set(fields)) != len(fields) or not required <= set(fields):
            raise ValueError()
        result, footer = [], None
        for values in rows:
            if not values or not any(values):
                continue
            if values[0].startswith('File Creation Time:'):
                if footer is not None:
                    raise ValueError()
                footer = values[0].split(':', 1)[1].strip()
                continue
            if footer is not None or len(values) != len(fields):
                raise ValueError()
            row = {k: v.strip() for k, v in zip(fields, values)}
            if row['Test Issue'] not in ('Y', 'N') or row['ETF'] not in ('Y', 'N'):
                raise ValueError()
            symbol = row['Symbol' if label == 'nasdaq' else 'ACT Symbol'].upper()
            aliases = ({row['CQS Symbol'].upper(), row['NASDAQ Symbol'].upper()} - {''}
                       if label == 'other' else {symbol})
            result.append({'symbol': symbol, 'security_name': row['Security Name'],
                'source': label, 'test_issue': row['Test Issue'], 'etf': row['ETF'],
                'aliases': sorted(aliases)})
        created = datetime.strptime(footer, '%m%d%Y%H:%M').replace(tzinfo=ET)
        # Explicit freshness bound; prior close/weekend files may be usable.
        if not result or not timedelta(0) <= at-created <= timedelta(days=7):
            raise ValueError()
        return result, footer
    except (ValueError, TypeError, IndexError, KeyError, UnicodeError, csv.Error):
        raise CatalogError('catalog_structure_or_freshness_invalid') from None


class DirectoryCatalog:
    """Immutable source facts, with raw bytes revalidated on every reopen/read."""
    def __init__(self, bodies, receipts):
        if set(bodies) != set(SOURCES) or set(receipts) != set(SOURCES):
            raise CatalogError('catalog_source_set_invalid')
        self.bodies = dict(bodies)
        self.receipts = freeze(receipts)
        self.path = None
        self._build()
        self._parsed_bodies = dict(self.bodies)
        self._parsed_receipts, self._parsed_public = self.receipts, self.public
        self._parsed_id, self._parsed_symbols = self.catalog_id, self.symbols
        self._validated_path, self._artifact_bytes = None, None

    def _build(self):
        rows, sources = [], {}
        for label, url in SOURCES.items():
            receipt = plain(self.receipts[label])
            if (set(receipt) != {'url', 'started_at_utc', 'retrieved_at_utc', 'synthetic', 'http'}
                    or receipt['url'] != url or type(receipt['synthetic']) is not bool):
                raise CatalogError('catalog_receipt_invalid')
            at, began = timestamp(receipt['retrieved_at_utc']), timestamp(receipt['started_at_utc'])
            http = receipt['http']
            if (not 0 <= (at-began).total_seconds() <= 10
                    or set(http) != {'status', 'final_url', 'body_complete'}
                    or type(http['status']) is not int or http['status'] != 200
                    or http['final_url'] != url or http['body_complete'] is not True):
                raise CatalogError('catalog_http_or_timing_invalid')
            parsed, footer = _rows(self.bodies[label], label, at)
            rows.extend(parsed)
            sources[label] = {**receipt, 'sha256': hashlib.sha256(self.bodies[label]).hexdigest(),
                'bytes': len(self.bodies[label]), 'file_creation_time': footer}
        symbols = [r['symbol'] for r in rows]
        if len(set(symbols)) != len(symbols):
            raise CatalogError('catalog_duplicate_symbol')
        eligible = sorted(r['symbol'] for r in rows if re.fullmatch('[A-Z][A-Z0-9]{0,9}', r['symbol'])
            and r['test_issue'] == r['etf'] == 'N' and not set(r['aliases'])-{r['symbol']})
        if not eligible:
            raise CatalogError('catalog_no_supported_exact_symbols')
        self.public = freeze({'contract': 'integrated-exact-directory-v1', 'sources': sources,
            'symbols': eligible, 'maximum_footer_age_days': 7,
            'scope': 'exact_identity_eligibility_not_daily_screen_or_broker_tradability'})
        self.catalog_id = 'nasdaq-exact-'+digest(self.public)
        self.symbols = tuple(eligible)

    def persist(self, folder):
        folder = Path(folder)
        folder.mkdir(exist_ok=False)
        for label in SOURCES:
            (folder/(label+'.txt')).write_bytes(self.bodies[label])
        (folder/'catalog.json').write_text(canonical({'catalog_id': self.catalog_id,
            'receipts': plain(self.receipts), 'public': plain(self.public)}), encoding='utf-8')
        return self.load(folder)

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        if (folder.is_symlink() or not folder.is_dir()
                or {p.name for p in folder.iterdir()} != {'catalog.json', 'nasdaq.txt', 'other.txt'}
                or any(p.is_symlink() or not p.is_file() for p in folder.iterdir())):
            raise CatalogError('catalog_artifacts_invalid')
        from .controller_bootstrap import strict_json
        meta = folder/'catalog.json'
        if meta.stat().st_size > 2*MAX_BYTES:
            raise CatalogError('catalog_artifacts_invalid')
        metadata_bytes = meta.read_bytes()
        value = strict_json(metadata_bytes.decode('utf-8'))
        if set(value) != {'catalog_id', 'receipts', 'public'}:
            raise CatalogError('catalog_artifacts_invalid')
        bodies = {}
        for label in SOURCES:
            p = folder/(label+'.txt')
            if p.stat().st_size > MAX_BYTES:
                raise CatalogError('catalog_body_invalid')
            bodies[label] = p.read_bytes()
        result = cls(bodies, value['receipts'])
        if result.catalog_id != value['catalog_id'] or canonical(result.public) != canonical(value['public']):
            raise CatalogError('catalog_artifacts_changed')
        result.path = folder.resolve()
        result._validated_path = result.path
        result._artifact_bytes = {'catalog.json': metadata_bytes,
            **{label+'.txt': raw for label, raw in bodies.items()}}
        return result

    def validate(self):
        # Parsed fields are immutable. Re-read ALL persisted bytes on every
        # validation; equality with the already fully parsed bytes proves the
        # same facts without rebuilding thousands of directory rows per pump.
        # No mtime/size-only cache or relaxed identity/freshness check is used.
        if (self.bodies != self._parsed_bodies or self.receipts is not self._parsed_receipts
                or self.public is not self._parsed_public or self.catalog_id != self._parsed_id
                or self.symbols != self._parsed_symbols or self.path != self._validated_path):
            raise CatalogError('catalog_changed')
        if self.path is not None:
            folder = self.path
            if (folder.is_symlink() or not folder.is_dir()
                    or {p.name for p in folder.iterdir()} != set(self._artifact_bytes)
                    or any(p.is_symlink() or not p.is_file() for p in folder.iterdir())):
                raise CatalogError('catalog_artifacts_invalid')
            for name, expected in self._artifact_bytes.items():
                path = folder/name
                if path.stat().st_size != len(expected) or path.read_bytes() != expected:
                    raise CatalogError('catalog_artifacts_changed')
        return self


def _stop(child):
    if child.poll() is None:
        child.terminate()
    try:
        child.wait(timeout=1)
    except subprocess.TimeoutExpired:
        child.kill(); child.wait(timeout=2)


def acquire_catalog(*, deadline, clock=None, allow_network=False, synthetic=None, hard_seconds=10):
    """Two fixed-source children, each with independent parent/child deadlines.

    Caller must invoke this after credential acceptance and within its frozen
    bootstrap window. No journal or filesystem artifact is created by this API.
    A synthetic scenario denies network in each child. No retry/fallback exists.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    if (type(allow_network) is not bool or synthetic is None and not allow_network
            or isinstance(hard_seconds, bool) or not isinstance(hard_seconds, (int, float))
            or not .05 <= hard_seconds <= 10):
        raise CatalogError('catalog_network_or_limit_not_authorized')
    if synthetic is not None and set(synthetic) != set(SOURCES):
        raise CatalogError('catalog_source_set_invalid')
    bodies, receipts, attempts = {}, {}, []
    for label, url in SOURCES.items():
        began = clock(); remaining = (deadline-began).total_seconds()
        if not 0 < remaining <= 61:
            raise CatalogError('catalog_bootstrap_window_ended', attempts)
        bound = min(hard_seconds, remaining)
        job = {'url': url, 'hard_seconds': bound,
            'synthetic': synthetic[label] if synthetic is not None else None}
        child = subprocess.Popen([sys.executable, '-I', '-B',
            str(Path(__file__).with_name('integrated_catalog_worker.py'))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            output, _ = child.communicate(json.dumps(job).encode(), timeout=bound)
            if child.returncode or len(output) > 6_000_000:
                raise CatalogError('catalog_hard_deadline' if child.returncode == 124 else 'catalog_worker_failed')
            from .controller_bootstrap import strict_json
            value = strict_json(output.decode())
            if set(value) != {'body_b64', 'status', 'final_url', 'body_complete'}:
                raise CatalogError('catalog_worker_protocol_invalid')
            raw = base64.b64decode(value.pop('body_b64'), validate=True)
            done = clock()
            if not began <= done < deadline or (done-began).total_seconds() > bound:
                raise CatalogError('catalog_bootstrap_window_ended')
            receipt = {'url': url, 'started_at_utc': utc_text(began), 'retrieved_at_utc': utc_text(done),
                'synthetic': synthetic is not None, 'http': value}
            attempts.append({'source': label, 'outcome': 'returned', 'receipt': receipt,
                'body_sha256': hashlib.sha256(raw).hexdigest(), 'body_bytes': len(raw),
                'body_b64': base64.b64encode(raw).decode()})
            # Reject a bad first source before spending the second retrieval.
            if (type(value['status']) is not int or value['status'] != 200
                    or value['final_url'] != url or value['body_complete'] is not True):
                raise CatalogError('catalog_http_or_timing_invalid')
            _rows(raw, label, done)
            bodies[label], receipts[label] = raw, receipt
        except BaseException as error:
            _stop(child)
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            code = (error.code if isinstance(error, CatalogError) else
                'catalog_hard_deadline' if isinstance(error, subprocess.TimeoutExpired) else 'catalog_worker_failed')
            attempts.append({'source': label, 'outcome': code, 'returncode': child.returncode,
                'owned_child_exit_observed': child.poll() is not None})
            raise CatalogError(code, attempts) from None
        finally:
            if child.stdin is not None: child.stdin.close()
            if child.stdout is not None: child.stdout.close()
    return DirectoryCatalog(bodies, receipts)
