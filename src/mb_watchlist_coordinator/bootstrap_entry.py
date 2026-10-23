"""Private-pipe, deadline-bound fresh-bootstrap entry; no quote/feed dispatch."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import threading

from .authenticated_startup import StartupError, receive_password, CODES as AUTH_CODES
from .controller_bootstrap import (BootstrapSettings, BootstrapError, bootstrap_fresh,
    CONTRACT, CODES, EXPECTED_HELPERS, strict_json)
from .installed_startup_probe import _silence, inspect_dependencies
from .sampling_requests import digest


def run_entry(configuration, configuration_sha256, *, stream=None, clock=None,
              inventory=None, secure_api=None, fault_hook=None, startup_seconds=8, hard_seconds=60):
    """One-shot bootstrap proof. A future controller uses bootstrap_fresh in place.

    Injectable APIs are trusted offline test seams, not command-line modes.
    Only a fixed safe receipt reaches the inherited stdout pipe.
    """
    channel = os.dup(1)
    _silence()
    clock = clock or (lambda: datetime.now(timezone.utc))
    done, authenticated = threading.Event(), threading.Event()
    lock = threading.Lock()
    emitted = False
    safe_sha = configuration_sha256 if isinstance(configuration_sha256, str) and re.fullmatch('[0-9a-f]{64}', configuration_sha256) else None
    state = {'contract': CONTRACT, 'configuration_sha256': safe_sha,
        'result': 'FAILED', 'reason': 'configuration_invalid', 'native_run_registered': False,
        'quote_dispatches_started': 0, 'feed_attempts_started': 0, 'client_close_invoked': False}
    def emit(reason=None):
        nonlocal emitted
        with lock:
            if emitted:
                return
            if reason:
                state.update(result='FAILED', reason=reason)
            raw = (json.dumps(state, sort_keys=True)+'\n').encode()
            os.write(channel, raw)
            emitted = True
    def watchdog(event, seconds, reason):
        if not event.wait(seconds):
            try:
                emit(reason)
            finally:
                os._exit(124)
    session = password = None
    try:
        if safe_sha is None or not 0 < startup_seconds <= 8 or not 0 < hard_seconds <= 60:
            raise BootstrapError('configuration_invalid')
        threading.Thread(target=watchdog, args=(done, hard_seconds, 'bootstrap_deadline_ended'), daemon=True).start()
        threading.Thread(target=watchdog, args=(authenticated, startup_seconds, 'credential_deadline_ended'), daemon=True).start()
        p = Path(configuration)
        if not p.is_file() or p.stat().st_size > 2_000_000:
            raise BootstrapError('configuration_invalid')
        raw = strict_json(p.read_text(encoding='utf-8'))
        raw['catalog_symbols'] = tuple(raw['catalog_symbols'])
        plan = BootstrapSettings(**raw).plan()
        if plan.configuration_sha256 != configuration_sha256:
            raise BootstrapError('inputs_changed')
        plan.fresh(clock)
        observed = (inventory or inspect_dependencies)(EXPECTED_HELPERS)
        if observed.get('qualified') is not True or digest(observed) != plan.settings.dependency_sha256:
            raise BootstrapError('dependency_rejected')
        password = receive_password(sys.stdin.buffer if stream is None else stream, plan.settings.nonce)
        def stage(name):
            if name == 'credentials_accepted':
                authenticated.set()
            if name == 'initial_poll_run_registered':
                state['native_run_registered'] = True
            if fault_hook:
                fault_hook(name)
        session = bootstrap_fresh(plan, password, clock=clock, inventory=inventory,
            secure_api=secure_api, fault_hook=stage)
        state.update(result='PASS', reason='bootstrap_pass')
        return 0
    except (BootstrapError, StartupError) as error:
        state['reason'] = error.code if error.code in CODES | AUTH_CODES else 'initialization_failed'
        return 70
    except KeyboardInterrupt:
        state['reason'] = 'operator_interrupted'
        return 130
    except Exception:
        state['reason'] = 'initialization_failed'
        return 70
    finally:
        if password is not None:
            password[:] = b'\0'*len(password)
            password.clear()
        if session is not None:
            state['client_close_invoked'] = True
            session.close()
        authenticated.set()
        done.set()
        emit()
        os.close(channel)


def parse_receipt(raw, configuration_sha256):
    """No unexpected child text/exception is returned or echoed to a caller."""
    try:
        if len(raw) > 8192:
            raise ValueError()
        value = strict_json(raw)
        if (set(value) != {'contract', 'configuration_sha256', 'result', 'reason',
                'native_run_registered', 'quote_dispatches_started', 'feed_attempts_started', 'client_close_invoked'}
                or value['contract'] != CONTRACT or value['configuration_sha256'] != configuration_sha256
                or value['result'] not in ('PASS', 'FAILED') or value['reason'] not in CODES | AUTH_CODES
                or type(value['native_run_registered']) is not bool or type(value['client_close_invoked']) is not bool
                or type(value['quote_dispatches_started']) is not int or value['quote_dispatches_started'] != 0
                or type(value['feed_attempts_started']) is not int or value['feed_attempts_started'] != 0
                or (value['result'] == 'PASS') != (value['reason'] == 'bootstrap_pass')
                or value['result'] == 'PASS' and not (value['native_run_registered'] and value['client_close_invoked'])):
            raise ValueError()
        return value
    except Exception:
        raise BootstrapError('initialization_failed') from None


def main():
    if len(sys.argv) != 3:
        return 64
    return run_entry(sys.argv[1], sys.argv[2])


if __name__ == '__main__':
    raise SystemExit(main())
