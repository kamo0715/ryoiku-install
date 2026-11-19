"""Generate first-run secrets on the HOST, never on a user's computer.

Only the FTPS account can read INITIAL_ADMIN_CODE.txt under the blocked private
application data directory. An unauthenticated web request cannot obtain it.
"""
import base64
import fcntl
import hashlib
import os
from pathlib import Path
import secrets
import tempfile


class BootstrapError(Exception):
    pass


def _atomic_private_write(path: Path, content: str):
    fd, temp = tempfile.mkstemp(prefix='.init-', dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def ensure_initial_config(app_dir):
    """Create first-time configuration safely; never reset existing data.

    Does not create any account or expose keys in HTTP responses.  If an
    existing database is found without .env, fail closed to avoid key loss.
    """
    app_dir = Path(app_dir)
    env_path = app_dir / '.env'
    data_dir = app_dir / 'data'
    code_path = data_dir / 'INITIAL_ADMIN_CODE.txt'
    if env_path.is_symlink() or data_dir.is_symlink():
        raise BootstrapError('Unsafe installation path')
    if env_path.is_file():
        return False
    if env_path.exists():
        raise BootstrapError('Unexpected configuration path')
    try:
        os.umask(0o077)
        data_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
        os.chmod(data_dir, 0o700)
        fd = os.open(app_dir / '.initialization.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd,'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if env_path.is_file():
                return False
            if env_path.is_symlink() or data_dir.is_symlink() or code_path.is_symlink():
                raise BootstrapError('Unsafe installation path')
            if any(data_dir.rglob('*.sqlite*')) or any(data_dir.rglob('*.db')):
                raise BootstrapError('Existing database without encryption key')
            secret = secrets.token_urlsafe(48)
            key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii')
            token = secrets.token_urlsafe(48)
            token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
            # Write the token first, then publish .env atomically: an interrupted
            # installation cannot expose a complete configuration without a code.
            _atomic_private_write(code_path, token + '\n')
            _atomic_private_write(env_path, '\n'.join((
                'APP_SECRET=' + secret,
                'DATA_ENCRYPTION_KEY=' + key,
                'APP_COOKIE_SECURE=true',
                'APP_SETUP_TOKEN_SHA256=' + token_hash,
                'LOLI_CGI_MODE=true',
                '',
            )))
            return True
    except (OSError, ValueError) as exc:
        raise BootstrapError('Cannot create secure first-run configuration') from exc
