"""Read-only ownership classifier for app-created Silo and compat identities.

Requires a fresh exclusive account/profile reservation and a complete frozen
census. Callers separately validate reservation, source, workers and playback.
"""
from dataclasses import dataclass
import hashlib
import json
import re
import copy
import math


class OwnershipError(ValueError):
    pass


REQUEST_CENSUS_SQL = """BEGIN READ ONLY; SET LOCAL statement_timeout='3000ms';
SELECT json_build_object(
 'installation',(SELECT value FROM server_settings WHERE key='diagnostics.server_instance_id'),
 'rows',COALESCE((SELECT json_agg(row_to_json(t)) FROM
   (SELECT id::text,device_name,client_purpose,status,approved_by_user_id,
           approved_profile_id,auth_session_id,match_code,user_code_hash
    FROM device_login_requests ORDER BY id LIMIT 200)t),'[]'::json),
 'count',(SELECT count(*) FROM device_login_requests)); ROLLBACK;"""


def census_with_requests(driver, binding):
    """Bracket request rows with stable auth censuses, bounded to three tries.

    App approval consumption creates its auth row between the independent SQL
    reads. Retry read-only capture when auth rows move; never relax the
    subsequent ownership checks or replay approval to repair an observation.
    """
    for _ in range(3):
        doc = driver.census(binding)
        if 'requests' in doc:
            return doc
        server = driver.server
        raw = driver.io.command(['docker', 'exec', '-i', server['names']['pg'],
                                 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
                                 '-h', '127.0.0.1', '-U', 'postgres', '-d', 'silo_test'],
                                driver.left(), REQUEST_CENSUS_SQL.encode(), limit=4 << 20)
        requests = json.loads(raw)
        if (requests['installation'] != binding['server']['identity'] or
                requests['count'] != len(requests['rows']) or requests['count'] > 200):
            raise OwnershipError('request census boundary')
        after = driver.census(binding)
        if doc['auth'] == after['auth']:
            return {**doc, 'requests': requests['rows']}
    raise OwnershipError('request census did not stabilize')


@dataclass(frozen=True)
class OwnedRows:
    app_auth_id: str | None
    compat_auth_id: str | None
    compat_token: str | None
    playback_id: str | None
    app_request_id: str | None
    compat_request_id: str | None


def _index(rows, key):
    result = {}
    for row in rows:
        value = row[key]
        if not isinstance(value, str) or not value or value in result:
            raise OwnershipError('invalid or duplicate census identity')
        result[value] = row
    return result


def _one(rows, kind):
    if len(rows) > 1:
        raise OwnershipError('multiple ' + kind + ' rows')
    return rows[0] if rows else None


def inspect_owned(doc, *, namespace, account, profile, baselines, terminal_owner=None):
    """Bind both app and Quick Connect logins by consumed request FK rows.

    Baselines hold complete rows. Controller rows belong in the auth baseline
    after independent gate validation. Compat has no login-session SQL column;
    its sole fresh scoped row is accepted only within an exclusive reservation
    after Quick Connect is consumed and linked to its own fresh auth row.
    """
    if not re.fullmatch(r'holderqa[0-9]{5,10}', namespace):
        raise OwnershipError('invalid namespace')
    keys = {'auth': 'id', 'requests': 'id', 'compat': 'token', 'playback': 'ID'}
    current, fresh = {}, {}
    if set(baselines) != set(keys):
        raise OwnershipError('incomplete baseline')
    for name, key in keys.items():
        now = _index(doc[name], key)
        before = _index(baselines[name], key)
        if any(now.get(identity) != row for identity, row in before.items()):
            raise OwnershipError('historical row changed')
        current[name] = now
        fresh[name] = [row for identity, row in now.items() if identity not in before]
    requests = fresh['requests']
    if any(r['device_name'] != namespace or r['client_purpose'] not in
           ('device_login', 'jellyfin_quick_connect') for r in requests):
        raise OwnershipError('unrelated device request')
    app = _one([r for r in requests if r['client_purpose'] == 'device_login'], 'app request')
    quick = _one([r for r in requests if r['client_purpose'] == 'jellyfin_quick_connect'], 'compat request')
    linked = set()
    for row in requests:
        if row['status'] in ('approved', 'consumed') and row['approved_by_user_id'] != account:
            raise OwnershipError('request approved by different account')
        if row['client_purpose'] == 'jellyfin_quick_connect' and row['status'] in ('approved', 'consumed') and row['approved_profile_id'] != profile:
            raise OwnershipError('wrong approved profile')
        session = row.get('auth_session_id')
        if row['status'] == 'consumed':
            if not session or session not in current['auth'] or session in linked:
                raise OwnershipError('missing or duplicate request session')
            auth = current['auth'][session]
            if auth in baselines['auth'] or auth['user_id'] != account or auth['device_name'] != namespace:
                raise OwnershipError('request session identity mismatch')
            linked.add(session)
        elif session:
            raise OwnershipError('unconsumed request has session')
    if {r['id'] for r in fresh['auth']} != linked:
        raise OwnershipError('unlinked fresh auth session')
    compat = _one(fresh['compat'], 'compat session')
    if compat and (not quick or quick['status'] != 'consumed' or compat['streamapp_user_id'] != account or compat['profile_id'] != profile):
        raise OwnershipError('compat session ownership mismatch')
    playback = _one(fresh['playback'], 'playback session')
    if playback:
        if compat:
            valid = playback.get('CompatToken') == compat['token'] and playback.get('ClientDeviceID') == namespace
        else:
            # The caller has checked the full sampler recipe against a completed,
            # same-binding negotiate receipt. Scope/terminal flags alone never suffice.
            proof = terminal_owner or {}
            valid = (proof.get('session') == playback['ID'] and
                     proof.get('token') == playback.get('CompatToken') and
                     proof.get('device') == namespace == playback.get('ClientDeviceID') and
                     proof.get('account') == account and proof.get('profile') == profile and
                     playback.get('Terminal') is True and
                     playback.get('TerminalAuthoritative') is True)
        if not valid:
            raise OwnershipError('playback identity mismatch')
    return OwnedRows(app.get('auth_session_id') if app else None,
                     quick.get('auth_session_id') if quick else None,
                     compat['token'] if compat else None,
                     playback['ID'] if playback else None,
                     app['id'] if app else None, quick['id'] if quick else None)


def _require_run_identity(driver, binding):
    namespace = binding['correlation']['device_id']
    if not re.fullmatch(r'holderqa[0-9]{5,10}', namespace) or any(
            value != namespace for value in (driver.config.get('user_agent'),
            driver.config.get('device_id'), binding['correlation'].get('user_agent'))):
        raise OwnershipError('run identity mismatch')


def approve_app_request(driver, binding, *, baselines, user_code, before_post=None, approval_call=None):
    """Approve the app's observed request with an existing verified controller.

    Called only inside the durable login operation after its intent is written.
    The code must come from the app's own screen/relay, never a DB hash.
    A transport error remains ambiguous for the outer lifecycle to reconcile.
    """
    _require_run_identity(driver, binding)
    if not isinstance(user_code, str) or not re.fullmatch(r'[0-9]{4}-?[0-9]{4}', user_code):
        raise OwnershipError('invalid app user code')
    doc = census_with_requests(driver, binding)
    driver.gate.validate(driver.config, binding, doc)
    owned = inspect_owned(doc, namespace=binding['correlation']['device_id'],
                          account=int(binding['server']['account']),
                          profile=binding['server']['profile'], baselines=baselines)
    if not owned.app_request_id:
        raise OwnershipError('app request absent')
    request = next(r for r in doc['requests'] if r['id'] == owned.app_request_id)
    if request['status'] in ('approved', 'consumed'):
        return owned
    if request['status'] != 'pending':
        raise OwnershipError('app request cannot be approved')
    if hashlib.sha256(user_code.replace('-', '').encode()).hexdigest() != request.get('user_code_hash'):
        raise OwnershipError('on-screen code hash does not identify app request')
    _, controller = driver.gate.controller(driver.config)
    if controller['phase'] != 'verified':
        raise OwnershipError('controller unavailable')
    lookup = driver.api('GET', '/api/v2/auth/device?code=' + user_code, native=True)
    if (lookup.get('status') != 'pending' or lookup.get('device_name') != binding['correlation']['device_id']
            or lookup.get('client_purpose') != 'device_login'
            or lookup.get('match_code') != request.get('match_code')):
        raise OwnershipError('on-screen code is not the owned app request')
    if before_post is not None:
        before_post()
    if approval_call is None:
        response = driver.api('POST', '/api/v2/auth/device/approve',
                              {'code': user_code}, native=True)
    else:
        response = approval_call(user_code)
    if response.get('status') != 'approved':
        raise OwnershipError('approval not confirmed')
    doc = census_with_requests(driver, binding)
    driver.gate.validate(driver.config, binding, doc)
    owned = inspect_owned(doc, namespace=binding['correlation']['device_id'],
                          account=int(binding['server']['account']),
                          profile=binding['server']['profile'], baselines=baselines)
    request = next(r for r in doc['requests'] if r['id'] == owned.app_request_id)
    if request['status'] not in ('approved', 'consumed'):
        raise OwnershipError('approval census unconfirmed')
    return owned


def revoke_owned_auth(driver, binding, *, baselines, auth_id):
    """Revoke one proven app/compat auth row; never use account-wide logout.

    Called inside the durable cleanup intent while its controller remains live.
    Transport.db must enforce installation/count attestation and driver.census
    supplies the source and deadline guards; verify the resulting row anew.
    """
    _require_run_identity(driver, binding)
    doc = census_with_requests(driver, binding)
    driver.gate.validate(driver.config, binding, doc)
    args = dict(namespace=binding['correlation']['device_id'],
                account=int(binding['server']['account']),
                profile=binding['server']['profile'], baselines=baselines)
    args['terminal_owner'] = _terminal_owner(driver, binding, doc)
    owned = inspect_owned(doc, **args)
    if (not isinstance(auth_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,128}', auth_id)
            or auth_id not in (owned.app_auth_id, owned.compat_auth_id)):
        raise OwnershipError('auth row not owned')
    row = next(r for r in doc['auth'] if r['id'] == auth_id)
    if not row['revoked']:
        _, controller = driver.gate.controller(driver.config)
        if controller['phase'] != 'verified':
            raise OwnershipError('controller unavailable')
        driver.api('DELETE', '/api/v2/auth/sessions/' + auth_id,
                   want=204, native=True)
    check = census_with_requests(driver, binding)
    driver.gate.validate(driver.config, binding, check)
    args['terminal_owner'] = _terminal_owner(driver, binding, check)
    verified = inspect_owned(check, **args)
    if not next(r for r in check['auth'] if r['id'] == auth_id)['revoked']:
        raise OwnershipError('revocation unconfirmed')
    return verified


def _terminal_owner(driver, binding, doc):
    validator = getattr(driver, '_terminal_owner', None)
    return validator(binding, doc) if validator else None


class DurableAppAuth:
    """Auth operations inside a prepared native_run Adapter's frozen run.

    The caller supplies the existing verified driver and the code actually
    displayed by the installed app. Media stop, server verification, controller
    cleanup and public app restore remain native_run cleanup responsibilities.
    """

    def __init__(self, adapter, driver, baselines):
        from qa_durable import RunLock
        self.adapter, self.driver, self.baselines = adapter, driver, copy.deepcopy(baselines)
        self.baseline_sha256 = hashlib.sha256(json.dumps(self.baselines, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.lock_type = RunLock
        if adapter.binding['source'].get('flow') != 'app_owned':
            raise OwnershipError('app-owned flow required')
        if set(baselines) != {'auth', 'requests', 'compat', 'playback'}:
            raise OwnershipError('incomplete auth baseline')

    def _owned(self, binding):
        doc = census_with_requests(self.driver, binding)
        self.driver.gate.validate(self.driver.config, binding, doc)
        owned = inspect_owned(doc, namespace=binding['correlation']['device_id'],
                              account=int(binding['server']['account']),
                              profile=binding['server']['profile'], baselines=self.baselines,
                              terminal_owner=_terminal_owner(self.driver, binding, doc))
        return doc, owned

    def _remaining_for_driver(self, deadline):
        remaining = self.adapter._remaining(deadline)
        if hasattr(self.driver, 'left'):
            remaining = min(remaining, self.driver.left())
        return remaining

    def _operation(self, action, fields, perform, reconcile, deadline):
        """Independent auth receipt avoids nesting native_run lifecycle writes."""
        from qa_durable import atomic_receipt, verify_receipt
        from experiments.onroku_audio.native_run import AmbiguousOperation
        root = self.adapter.root
        path = root / 'app-auth.json'
        with self.lock_type(root / 'app-auth.lock', timeout=0):
            if action == 'approve_app' and (
                    (root / 'cleanup-claim.json').exists() or
                    self.adapter._state()['cleanup_started']):
                raise OwnershipError('cleanup already claimed')
            if path.exists():
                state = verify_receipt(path, self.adapter.manifest)
                if (state.get('binding_sha256') != self.adapter.binding_hash or
                        state.get('baseline_sha256') != self.baseline_sha256 or
                        not isinstance(state.get('operations'), dict)):
                    raise OwnershipError('auth receipt binding mismatch')
            else:
                state = {'binding_sha256': self.adapter.binding_hash,
                         'baseline_sha256': self.baseline_sha256, 'operations': {}}
            for name, row in state['operations'].items():
                if name not in ('approve_app', 'revoke_app', 'revoke_compat') or not isinstance(row, dict) or set(row) not in ({'intent'}, {'intent', 'result'}):
                    raise OwnershipError('invalid auth operation receipt')
                expected = {'operation_id', 'binding_sha256', 'request_id', 'code_hash'} if name == 'approve_app' else {'operation_id', 'binding_sha256', 'auth_id'}
                candidate = row['intent']
                if (not isinstance(candidate, dict) or set(candidate) != expected or
                        candidate.get('operation_id') != self.adapter.manifest.run_id + ':' + name or
                        candidate.get('binding_sha256') != self.adapter.binding_hash):
                    raise OwnershipError('invalid auth intent')
            entry = state['operations'].get(action)
            if entry:
                intent = entry['intent']
                if any(intent.get(k) != v for k, v in fields.items()):
                    raise OwnershipError('auth operation identity changed')
                if intent.get('operation_id') != self.adapter.manifest.run_id + ':' + action or intent.get('binding_sha256') != self.adapter.binding_hash:
                    raise OwnershipError('auth intent binding mismatch')
                if 'result' in entry:
                    cached = entry['result']
                    if (not isinstance(cached, dict) or cached.get('status') != 'complete' or
                            any(cached.get(k) != intent[k] for k in ('operation_id', 'binding_sha256')) or
                            cached.get('request_id' if action == 'approve_app' else 'auth_id') !=
                            intent['request_id' if action == 'approve_app' else 'auth_id']):
                        raise OwnershipError('invalid cached auth result')
                    return copy.deepcopy(cached)
                self.driver._end(self._remaining_for_driver(deadline))
                result = reconcile(self.adapter.binding, intent)
            else:
                intent = {'operation_id': self.adapter.manifest.run_id + ':' + action,
                          'binding_sha256': self.adapter.binding_hash, **copy.deepcopy(fields)}
                entry = {'intent': intent}
                state['operations'][action] = entry
                atomic_receipt(path, self.adapter.manifest, state)
                self.driver._end(self._remaining_for_driver(deadline))
                result = perform(self.adapter.binding, intent)
            self.adapter._remaining(deadline)
            identity_key = 'request_id' if action == 'approve_app' else 'auth_id'
            if (not isinstance(result, dict) or
                    any(result.get(k) != intent[k] for k in ('operation_id', 'binding_sha256', identity_key)) or
                    result.get('status') != 'complete'):
                raise AmbiguousOperation('auth operation incomplete')
            entry['result'] = result
            atomic_receipt(path, self.adapter.manifest, state)
            return copy.deepcopy(result)

    def _guard_approval(self):
        if ((self.adapter.root / 'cleanup-claim.json').exists() or
                self.adapter._state()['cleanup_started']):
            raise OwnershipError('cleanup already claimed')

    def _post_approval(self, code):
        # qa_supervision writes cleanup-claim under watch.lock. Hold that same
        # lock through POST so a concurrent cleanup claim cannot cross the guard.
        deadline = self.adapter.manifest.start_mono + self.adapter.binding['setup_seconds']
        with self.lock_type(self.adapter.root / 'watch.lock',
                            timeout=self._remaining_for_driver(deadline)):
            self._remaining_for_driver(deadline)
            self._guard_approval()
            return self.driver.api('POST', '/api/v2/auth/device/approve',
                                   {'code': code}, native=True)

    def approve(self, user_code):
        """Persist exact request and code hash before controller approval IO."""
        from experiments.onroku_audio.native_run import AmbiguousOperation
        binding = self.adapter.binding
        _require_run_identity(self.driver, binding)
        if not isinstance(user_code, str) or not re.fullmatch(r'[0-9]{4}-?[0-9]{4}', user_code):
            raise OwnershipError('invalid app user code')
        deadline = self.adapter.manifest.start_mono + self.adapter.binding['setup_seconds']
        self.driver._end(self._remaining_for_driver(deadline))
        doc, owned = self._owned(binding)
        if not owned.app_request_id:
            raise OwnershipError('app request absent')
        row = next(r for r in doc['requests'] if r['id'] == owned.app_request_id)
        code_hash = hashlib.sha256(user_code.replace('-', '').encode()).hexdigest()
        if row.get('user_code_hash') != code_hash:
            raise OwnershipError('code does not match owned request')
        fields = {'request_id': owned.app_request_id, 'code_hash': code_hash}

        def verify(bound, intent):
            census, found = self._owned(bound)
            if found.app_request_id != intent['request_id']:
                raise OwnershipError('app request changed')
            request = next(r for r in census['requests'] if r['id'] == found.app_request_id)
            if request.get('user_code_hash') != intent['code_hash']:
                raise OwnershipError('app code changed')
            if request['status'] not in ('approved', 'consumed'):
                raise AmbiguousOperation('approval intent still pending')
            return {**{k: intent[k] for k in ('operation_id', 'binding_sha256')},
                    'status': 'complete', 'request_id': found.app_request_id}

        def perform(bound, intent):
            approved = approve_app_request(self.driver, bound, baselines=self.baselines,
                                           user_code=user_code, approval_call=self._post_approval)
            if approved.app_request_id != intent['request_id']:
                raise OwnershipError('approved request changed')
            return verify(bound, intent)

        return self._operation('approve_app', fields, perform, verify, deadline)

    def revoke(self, kind):
        """Revoke one exact owned session after supervised cleanup is claimed."""
        from experiments.onroku_audio.native_run import AmbiguousOperation
        if kind not in ('app', 'compat'):
            raise OwnershipError('invalid auth kind')
        binding = self.adapter.binding
        _require_run_identity(self.driver, binding)
        claim = self.adapter.root / 'cleanup-claim.json'
        from qa_durable import verify_receipt
        cleanup = verify_receipt(claim, self.adapter.manifest)
        deadline = cleanup['cleanup_deadline_mono']
        if (isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or
                not math.isfinite(deadline) or
                deadline > self.adapter.manifest.deadline_mono + self.adapter.plan['cleanup_grace']):
            raise OwnershipError('invalid cleanup deadline')
        self.driver._end(self._remaining_for_driver(deadline))
        doc, owned = self._owned(binding)
        auth_id = getattr(owned, kind + '_auth_id')
        if not auth_id:
            raise OwnershipError('auth session not established')
        fields = {'auth_id': auth_id}

        def verify(bound, intent):
            census, found = self._owned(bound)
            if getattr(found, kind + '_auth_id') != intent['auth_id']:
                raise OwnershipError('auth ownership changed')
            row = next(r for r in census['auth'] if r['id'] == intent['auth_id'])
            if not row['revoked']:
                raise AmbiguousOperation('revocation intent still pending')
            return {**{k: intent[k] for k in ('operation_id', 'binding_sha256')},
                    'status': 'complete', 'auth_id': intent['auth_id']}

        def perform(bound, intent):
            revoke_owned_auth(self.driver, bound, baselines=self.baselines,
                              auth_id=intent['auth_id'])
            return verify(bound, intent)

        return self._operation('revoke_' + kind, fields, perform, verify, deadline)
