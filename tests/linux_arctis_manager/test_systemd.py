import subprocess
from unittest.mock import patch

import pytest

from linux_arctis_manager import systemd
from linux_arctis_manager.constants import SYSTEMD_SERVICE_NAME


class FakeSystemctl:
    '''Records `systemctl --user` calls and answers state queries.'''

    def __init__(self, enabled=True, active=False, failed=False, fail_on: str | None = None):
        self.state = {'is-enabled': enabled, 'is-active': active, 'is-failed': failed}
        self.fail_on = fail_on
        self.calls: list[str] = []

    def __call__(self, cmd, stdout=None, check=False):
        assert cmd[:2] == ['systemctl', '--user']
        verb = cmd[2]
        self.calls.append(verb)
        returncode = 0
        if verb in self.state:
            returncode = 0 if self.state[verb] else 1
        elif verb == self.fail_on:
            returncode = 1
        if check and returncode != 0:
            raise subprocess.CalledProcessError(returncode, cmd)
        return subprocess.CompletedProcess(cmd, returncode)


@pytest.fixture
def unit_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(systemd, 'HOME_SYSTEMD_SERVICE_FOLDER', tmp_path)
    monkeypatch.setattr(systemd, 'write_systemd_service', lambda path: None)
    return tmp_path


def run(fake, **kwargs):
    with patch('subprocess.run', side_effect=fake):
        return systemd.ensure_systemd_unit(**kwargs)


def test_failed_unit_is_reset_before_start(unit_dir):
    fake = FakeSystemctl(failed=True)
    assert run(fake, enable=True) is True
    assert fake.calls.index('reset-failed') < fake.calls.index('start')


def test_healthy_unit_is_not_reset(unit_dir):
    fake = FakeSystemctl()
    assert run(fake, enable=True) is True
    assert 'reset-failed' not in fake.calls
    assert 'start' in fake.calls


def test_active_unit_is_left_alone(unit_dir):
    fake = FakeSystemctl(active=True)
    assert run(fake, enable=True) is True
    assert 'start' not in fake.calls and 'restart' not in fake.calls


def test_active_unit_restarts_on_request(unit_dir):
    fake = FakeSystemctl(active=True)
    assert run(fake, enable=True, restart=True) is True
    assert 'restart' in fake.calls


def test_disabled_unit_is_enabled(unit_dir):
    fake = FakeSystemctl(enabled=False)
    assert run(fake, enable=True) is True
    assert 'enable' in fake.calls


def test_start_failure_returns_false_instead_of_raising(unit_dir):
    fake = FakeSystemctl(fail_on='start')
    assert run(fake, enable=True) is False


def test_missing_systemctl_returns_false(unit_dir):
    with patch('subprocess.run', side_effect=FileNotFoundError('systemctl')):
        assert systemd.ensure_systemd_unit(enable=True) is False


def test_template_does_not_restart_duplicate_daemon():
    template = systemd.systemd_service_template('/usr/bin/lam-daemon')
    assert f'RestartPreventExitStatus={systemd.EXIT_ALREADY_RUNNING}' in template
    assert 'After=pipewire.service pipewire-pulse.service' in template
    assert 'ExecStart=/usr/bin/lam-daemon' in template


def test_write_service_skips_reload_when_unchanged(tmp_path):
    path = tmp_path / SYSTEMD_SERVICE_NAME
    with patch('shutil.which', return_value='/usr/bin/lam-daemon'), \
         patch('subprocess.run') as mock_run:
        systemd.write_systemd_service(path)
        assert mock_run.call_count == 1
        systemd.write_systemd_service(path)
        assert mock_run.call_count == 1
