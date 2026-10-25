"""Owned P7 setting rollback; injected transports perform authenticated requests.

Caller must hold the exclusive test reservation/private config lease across all
operations and retain controller credentials until restore confirms success.
A prepare failure with can_revoke_controller=True proves no PUT was attempted;
all post-write uncertainty and foreign receipts require recovery before revoke.
A GET of the pre-write value cannot fence a delayed PUT. Durable pending writes
resolve only when GET observes their target; no pending PUT is ever repeated.
Rechecks are not atomic CAS and cannot exclude unrelated administrator writes.
"""
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

KEY = 'jellyfin_compat.public_url'
ENDPOINT = '/api/v1/admin/settings/' + KEY


class SettingError(RuntimeError):
    can_revoke_controller = False

    def __init__(self, message, *, can_revoke_controller=False):
        super().__init__(message)
        self.can_revoke_controller = can_revoke_controller


def _origin(value):
    try:
        parsed = urlsplit(value)
        valid = (isinstance(value, str) and value and not any(c.isspace() for c in value)
                 and parsed.scheme in ('http', 'https') and parsed.hostname
                 and parsed.username is None and parsed.password is None
                 and not parsed.path and not parsed.query and not parsed.fragment
                 and parsed.port != 0 and value == parsed.scheme + '://' + parsed.netloc)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise SettingError('nonempty HTTP(S) origin required')
    return value


class OwnedCompatSetting:
    def __init__(self, receipt_path, *, run_id, server_id, controller_id, get, put):
        self.path = Path(receipt_path)
        self.identity = dict(run_id=run_id, server_id=server_id, controller_id=controller_id)
        if not all(isinstance(v, str) and v.strip() for v in self.identity.values()):
            raise SettingError('run, server and controller identities required')
        self.get, self.put = get, put

    def _save(self, receipt, status):
        receipt = dict(receipt, status=status)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.stat().st_mode & 0o077:
            raise SettingError('receipt parent must be private')
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, delete=False) as output:
                name = output.name
                os.fchmod(output.fileno(), 0o600)
                json.dump(receipt, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, self.path)
            name = None
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if name is not None:
                Path(name).unlink(missing_ok=True)
        return {'status': status, 'can_revoke_controller': status == 'restored'}

    def _load(self):
        try:
            receipt = json.loads(self.path.read_text())
            if (receipt['identity'] != self.identity or receipt['endpoint'] != ENDPOINT
                    or self.path.stat().st_mode & 0o077):
                raise ValueError()
            _origin(receipt['old'])
            _origin(receipt['new'])
            if (receipt['pending'] not in (None, 'apply', 'restore')
                    or receipt['status'] not in ('prepared', 'apply-intent', 'applied',
                                                 'restore-intent', 'restored', 'conflict')):
                raise ValueError()
            if receipt['old'] == receipt['new']:
                raise ValueError()
            return receipt
        except (OSError, ValueError, KeyError, TypeError):
            raise SettingError('invalid or foreign setting receipt') from None

    def _current(self):
        try:
            response = self.get(ENDPOINT)
            if response['key'] != KEY:
                raise ValueError()
            return _origin(response['value'])
        except Exception:
            raise SettingError('setting GET failed; retain controller and receipt') from None

    def prepare(self, candidate):
        candidate = _origin(candidate)
        if self.path.exists():
            raise SettingError('receipt already exists; recover it before preparing')
        try:
            old = self._current()
            if old == candidate:
                raise SettingError('candidate must differ from previous origin')
            return self._save(dict(identity=self.identity, endpoint=ENDPOINT, old=old, new=candidate, pending=None), 'prepared')
        except Exception as error:
            raise SettingError('prepare failed before mutation', can_revoke_controller=True) from error

    def _write_and_observe(self, receipt, value, intent):
        receipt['pending'] = 'apply' if intent == 'apply-intent' else 'restore'
        self._save(receipt, intent)
        try:
            self.put(ENDPOINT, {'value': value})
        except Exception:
            pass  # An error may follow a successful server write. Resolve by GET.
        return self._current()

    def apply(self):
        receipt = self._load()
        if receipt['status'] != 'prepared':
            raise SettingError('apply already attempted; restore before another run')
        current = self._current()
        if current != receipt['old']:
            self._save(receipt, 'conflict')
            raise SettingError('setting changed before apply; retain controller')
        current = self._write_and_observe(receipt, receipt['new'], 'apply-intent')
        if current == receipt['new']:
            receipt['pending'] = None
            return self._save(receipt, 'applied')
        if current == receipt['old']:
            raise SettingError('apply may still commit; retain controller; never repeat PUT')
        self._save(receipt, 'conflict')
        raise SettingError('setting conflict after apply; retain controller')

    def restore(self):
        receipt = self._load()
        current = self._current()
        if receipt['pending'] == 'apply':
            if current == receipt['new']:
                receipt['pending'] = None
                self._save(receipt, 'applied')
            else:
                raise SettingError('apply completion unconfirmed; retain controller; never repeat PUT')
        if receipt['pending'] == 'restore':
            if current == receipt['old']:
                receipt['pending'] = None
                return self._save(receipt, 'restored')
            raise SettingError('restore completion unconfirmed; retain controller; never repeat PUT')
        if current == receipt['old']:
            return self._save(receipt, 'restored')
        if current != receipt['new']:
            self._save(receipt, 'conflict')
            raise SettingError('setting conflict; refusing overwrite; retain controller')
        current = self._write_and_observe(receipt, receipt['old'], 'restore-intent')
        if current == receipt['old']:
            receipt['pending'] = None
            return self._save(receipt, 'restored')
        if current != receipt['new']:
            self._save(receipt, 'conflict')
        raise SettingError('restoration unconfirmed; retain controller')
