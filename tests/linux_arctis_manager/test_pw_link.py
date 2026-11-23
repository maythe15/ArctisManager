import subprocess

from linux_arctis_manager.pw_link import PipeWireLinker, port_channel


def _completed(returncode: int = 0, stdout: str = '', stderr: str = ''):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_port_channel():
    assert port_channel('monitor_FL') == 'FL'
    assert port_channel('playback_FR') == 'FR'
    assert port_channel('playback_MONO') == 'MONO'


def test_output_ports_filters_by_node_name(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _completed(stdout=(
            'Arctis_Game:monitor_FL\n'
            'Arctis_Game:monitor_FR\n'
            'Arctis_Game_Other:monitor_FL\n'
            'alsa_output.headset:monitor_FL\n'
        ))

    monkeypatch.setattr(subprocess, 'run', fake_run)

    assert PipeWireLinker().output_ports('Arctis_Game') == ['monitor_FL', 'monitor_FR']
    assert calls == [['pw-link', '--output']]


def test_input_ports_returns_empty_on_failure(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda args, **kwargs: _completed(returncode=1))

    assert PipeWireLinker().input_ports('alsa_output.headset') == []


def test_link_succeeds_and_treats_existing_link_as_success(monkeypatch):
    results = iter([_completed(), _completed(returncode=1, stderr='failed to link ports: File exists')])
    monkeypatch.setattr(subprocess, 'run', lambda args, **kwargs: next(results))

    linker = PipeWireLinker()
    assert linker.link('Arctis_Game:monitor_FL', 'alsa_output.headset:playback_FL') is True
    assert linker.link('Arctis_Game:monitor_FL', 'alsa_output.headset:playback_FL') is True


def test_link_reports_failure(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda args, **kwargs: _completed(returncode=1, stderr='No such port'))

    assert PipeWireLinker().link('a:monitor_FL', 'b:playback_FL') is False


def test_missing_executable_is_handled(monkeypatch):
    def raise_missing(args, **kwargs):
        raise FileNotFoundError('pw-link')

    monkeypatch.setattr(subprocess, 'run', raise_missing)

    linker = PipeWireLinker()
    assert linker.output_ports('Arctis_Game') == []
    assert linker.link('a:monitor_FL', 'b:playback_FL') is False


def test_available_checks_path(monkeypatch):
    monkeypatch.setattr('linux_arctis_manager.pw_link.shutil.which', lambda name: None)
    assert PipeWireLinker().available() is False

    monkeypatch.setattr('linux_arctis_manager.pw_link.shutil.which', lambda name: '/usr/bin/pw-link')
    assert PipeWireLinker().available() is True
