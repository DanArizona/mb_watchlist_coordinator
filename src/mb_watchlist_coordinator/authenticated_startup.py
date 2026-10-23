"""Human-started credential bootstrap; secrets remain in memory/owned pipes.

The persistent credential convention remains mb_tools .ecfg plus its token DB.
No unattended decryption store, environment password, or plaintext file is added.
"""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import dataclass
from datetime import datetime, timezone
import getpass
import json
import logging
from pathlib import Path
import re
import warnings

from .sampling_requests import canonical, timestamp

MAX_FRAME_BYTES = 4096
MAX_PASSWORD_BYTES = 512
CODES = frozenset(('secret_handoff_invalid', 'credentials_unavailable',
    'credential_horizon', 'authorization_required', 'startup_failed',
    'provider_failed', 'provider_decode_failed', 'window_ended'))


class StartupError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in CODES else 'startup_failed'
        super().__init__(self.code)


class SessionPassword:
    """One manual controller session; clearing is best effort, not RAM erasure."""
    def __init__(self, password, configuration_sha256):
        try:
            value = password.encode('utf-8') if isinstance(password, str) else bytes(password)
            value.decode('utf-8')
            valid=re.fullmatch('[0-9a-f]{64}', configuration_sha256)
        except Exception:
            raise StartupError('secret_handoff_invalid') from None
        if not 1 <= len(value) <= MAX_PASSWORD_BYTES or not valid:
            raise StartupError('secret_handoff_invalid')
        self._value = bytearray(value)
        self.identity = {'contract': 'anonymous-stdin-secret-v1',
            'configuration_sha256': configuration_sha256}

    def __repr__(self):return '<SessionPassword redacted>'

    @classmethod
    def prompt(cls, configuration_sha256):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                password = getpass.getpass('Encrypted config password: ')
            return cls(password, configuration_sha256)
        except Exception:
            raise StartupError('credentials_unavailable') from None

    def frame(self, token):
        if not self._value or not re.fullmatch('[0-9a-f]{32}', token):
            raise StartupError('credentials_unavailable')
        value = bytearray(canonical({'contract': 'anonymous-stdin-secret-v1',
            'token': token, 'password': self._value.decode('utf-8')}).encode())
        if len(value) > MAX_FRAME_BYTES:
            raise StartupError('secret_handoff_invalid')
        return value

    def close(self):
        self._value[:] = b'\0'*len(self._value)
        self._value.clear()


def receive_password(stream, token):
    """Caller must enforce a hard process deadline while waiting for EOF."""
    raw = stream.read(MAX_FRAME_BYTES+1)
    try:
        frame = json.loads(raw)
        if (len(raw) > MAX_FRAME_BYTES or set(frame) != {'contract','token','password'}
                or frame['contract'] != 'anonymous-stdin-secret-v1' or frame['token'] != token
                or not isinstance(frame['password'],str)):
            raise ValueError()
        result = bytearray(frame['password'].encode('utf-8'))
        if not 1 <= len(result) <= MAX_PASSWORD_BYTES:
            raise ValueError()
        return result
    except Exception:
        raise StartupError('secret_handoff_invalid') from None


@dataclass(frozen=True)
class AuthStartupSettings:
    ecfg_path: str
    stop_at_utc: str
    request_timeout_seconds: int = 3
    startup_timeout_seconds: int = 8

    def payload(self):
        stop = timestamp(self.stop_at_utc)
        if (not Path(self.ecfg_path).is_absolute()
                or type(self.request_timeout_seconds) is not int or not 1 <= self.request_timeout_seconds <= 3
                or type(self.startup_timeout_seconds) is not int or not 1 <= self.startup_timeout_seconds <= 8):
            raise ValueError('Explicit credential path and bounded startup/request limits required')
        return {'contract':'authenticated-hot-startup-v1','ecfg_path':str(Path(self.ecfg_path).resolve()),
            'stop_at_utc':stop.isoformat(),'request_timeout_seconds':self.request_timeout_seconds,
            'startup_timeout_seconds':self.startup_timeout_seconds}


class _Discard:
    def write(self, value):return len(value)
    def flush(self):pass


@contextmanager
def _quiet():
    previous = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with redirect_stdout(_Discard()), redirect_stderr(_Discard()):yield
    finally:
        logging.disable(previous)


class _RejectAuthorization:
    def __init__(self):self.requested=False
    def __call__(self, _url):self.requested=True;return ''


class _SafeResponse:
    text = 'Quote request failed'
    def __init__(self, response, owner):
        self._response, self._owner = response, owner
        self.status_code, self.ok = int(response.status_code), bool(response.ok)
        if not 100 <= self.status_code <= 599:raise StartupError('provider_failed')
    def json(self):
        if not self.ok:return {}
        try:
            with _quiet():return self._response.json()
        except Exception:
            self._owner.halt_reason='provider_decode_failed'
            raise StartupError('provider_decode_failed') from None


class PreparedSchwabClient:
    def __init__(self, client, rejection, stop, clock):
        self._client, self._rejection, self._stop, self._clock = client, rejection, stop, clock
        self.halt_reason = None
    def __repr__(self):return '<PreparedSchwabClient redacted>'
    def quotes(self, symbols, *, fields):
        if self._rejection.requested:self.halt_reason='authorization_required'
        if self._clock() >= self._stop:self.halt_reason='window_ended'
        if self.halt_reason:raise StartupError(self.halt_reason)
        try:
            with _quiet():response = self._client.quotes(symbols,fields=fields)
            result = _SafeResponse(response,self)
            if result.status_code in (401,403) or self._rejection.requested:
                self.halt_reason='authorization_required'
            return result
        except Exception:
            self.halt_reason='authorization_required' if self._rejection.requested else 'provider_failed'
            raise StartupError(self.halt_reason) from None
    def close(self):
        try:
            with _quiet():self._client.close()
        except Exception:pass


def prepare_authenticated_client(settings, password, *, clock=None, secure_api=None):
    """Existing .ecfg/status/factory interfaces; no real credentials in tests."""
    clock = clock or (lambda:datetime.now(timezone.utc))
    settings.payload()
    stop = timestamp(settings.stop_at_utc)
    client = None
    try:
        if clock() >= stop:raise StartupError('window_ended')
        if secure_api is None:
            import mb_tools.schwab_secure as secure_api
        with _quiet():config = secure_api.load_secure_schwab_config(Path(settings.ecfg_path),password)
        required = stop+secure_api.DEFAULT_POLLING_REFRESH_MARGIN
        try:
            status=secure_api.read_schwab_token_status(config,observed_at=clock())
            status.require_refresh_valid_through(required)
        except Exception:raise StartupError('credential_horizon') from None
        rejection = _RejectAuthorization()
        with _quiet():client=secure_api.make_client_from_config(config,
            timeout=settings.request_timeout_seconds,call_on_auth=rejection)
        if rejection.requested:raise StartupError('authorization_required')
        if clock() >= stop:raise StartupError('window_ended')
        try:
            fresh=secure_api.read_schwab_token_status(config,observed_at=clock())
            fresh.require_refresh_valid_through(required)
        except Exception:raise StartupError('credential_horizon') from None
        result=PreparedSchwabClient(client,rejection,stop,clock)
        client=None
        return result
    except StartupError:
        raise
    except Exception:
        raise StartupError('startup_failed') from None
    finally:
        if client is not None:
            try:
                with _quiet():client.close()
            except Exception:pass
