import logging
import shutil
import subprocess
import sys
from pathlib import Path

from linux_arctis_manager.constants import (HOME_SYSTEMD_SERVICE_FOLDER,
                                            SYSTEMD_SERVICE_NAME)
from linux_arctis_manager.scripts.daemon import EXIT_ALREADY_RUNNING

logger = logging.getLogger('systemd')


def _systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(['systemctl', '--user', *args], stdout=subprocess.DEVNULL, check=check)


def is_systemd_unit_enabled() -> bool:
    try:
        subprocess.check_call(['systemctl', '--user', 'is-enabled', SYSTEMD_SERVICE_NAME], stdout=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        pass

    return False

def ensure_systemd_unit(enable: bool = False, restart: bool = False) -> bool:
    '''
    Write the user unit and, with `enable`, enable and start it.

    Returns False instead of raising when systemctl fails, so callers such as
    the GUI keep running and can report it.
    '''
    try:
        path = HOME_SYSTEMD_SERVICE_FOLDER / SYSTEMD_SERVICE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        write_systemd_service(path)
        if not enable:
            return True

        if _systemctl('is-enabled', SYSTEMD_SERVICE_NAME).returncode != 0:
            _systemctl('enable', SYSTEMD_SERVICE_NAME, check=True)

        is_active = _systemctl('is-active', SYSTEMD_SERVICE_NAME).returncode == 0
        if is_active and not restart:
            return True

        # After repeated daemon failures systemd refuses further starts with
        # "Start request repeated too quickly" until the unit is reset. An
        # explicit start from the user deserves a fresh attempt.
        if _systemctl('is-failed', SYSTEMD_SERVICE_NAME).returncode == 0:
            _systemctl('reset-failed', SYSTEMD_SERVICE_NAME)

        _systemctl('restart' if is_active else 'start', SYSTEMD_SERVICE_NAME, check=True)
        return True
    except (subprocess.CalledProcessError, OSError) as e:
        logger.warning('Could not start %s: %s. Check `journalctl --user -u %s`.', SYSTEMD_SERVICE_NAME, e, SYSTEMD_SERVICE_NAME)
        return False

def systemd_service_template(daemon_path: str | Path) -> str:
    return f'''[Unit]
Description=Arctis Manager
After=pipewire.service pipewire-pulse.service
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
ExecStart={daemon_path}
Restart=on-failure
RestartSec=5
RestartPreventExitStatus={EXIT_ALREADY_RUNNING}

[Install]
WantedBy=graphical-session.target'''

def write_systemd_service(path: Path) -> None:
    daemon_path = shutil.which('lam-daemon') or Path(sys.argv[0]).resolve().parent / 'lam-daemon'

    template = systemd_service_template(daemon_path)

    if path.exists() and path.read_text() == f'{template}\n':
        return

    with open(path, 'w') as f:
        f.writelines([f'{line}\n' for line in template.split('\n')])

    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
