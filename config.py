"""Validated, explicit runtime settings. No secrets are loaded from source files."""
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    environment: str
    data: Path
    admin: Path
    host: str
    port: int
    test_login: bool

    @classmethod
    def load(cls, env: Mapping[str, str], root: Path):
        mode = env.get('MOMIQ_ENV', 'local')
        if mode not in {'local', 'test', 'staging', 'production'}:
            raise ValueError('MOMIQ_ENV must be local, test, staging or production')
        raw_data = env.get('MOMIQ_DATA_DIR')
        if mode in {'staging', 'production'} and not raw_data:
            raise ValueError('Hosted environments require an explicit MOMIQ_DATA_DIR')
        data = Path(raw_data) if raw_data else root / 'data'
        if mode in {'staging', 'production'} and not data.is_absolute():
            raise ValueError('Hosted MOMIQ_DATA_DIR must be absolute')
        flag = env.get('MOMIQ_ALLOW_TEST_LOGIN', '1' if mode in {'local', 'test'} else '0')
        if flag not in {'0', '1'}:
            raise ValueError('MOMIQ_ALLOW_TEST_LOGIN must be 0 or 1')
        if mode == 'production' and flag == '1':
            raise ValueError('Test login is forbidden in production; use staging for test data')
        admin_default = root.parent / 'momiq_admin'
        if not admin_default.is_dir():
            admin_default = root.parent / 'momiq_admin_panel'
        port = int(env.get('MOMIQ_PORT', '8080'))
        if not 1 <= port <= 65535:
            raise ValueError('MOMIQ_PORT is outside 1..65535')
        data = data.resolve()
        admin = Path(env.get('MOMIQ_ADMIN_DIR', admin_default)).resolve()
        if data.is_relative_to(admin) or admin.is_relative_to(data):
            raise ValueError('Runtime data and public admin assets require separate directories')
        return cls(mode, data, admin, env.get('MOMIQ_HOST', '127.0.0.1'), port, flag == '1')
