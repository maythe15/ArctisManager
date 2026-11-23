import logging

import pytest

from linux_arctis_manager.constants import (
    PULSE_AUX_NODE_NAME,
    PULSE_CHAT_NODE_NAME,
    PULSE_GAME_NODE_NAME,
    PULSE_MEDIA_NODE_NAME,
    PULSE_MICROPHONE_NODE_NAME,
)

try:
    from linux_arctis_manager.pactl import PulseAudioManager
except FileNotFoundError as exc:
    pytest.skip(f'PulseAudio shared library is not available: {exc}', allow_module_level=True)


class FakeSink:
    def __init__(self, node_name: str, description: str, index: int = 1):
        self.index = index
        self.name = node_name
        self.proplist = {
            'node.name': node_name,
            'node.description': description,
        }


class FakeSinkInput:
    def __init__(self, stream_index: int, sink_index: int, app_name: str):
        self.index = stream_index
        self.name = app_name
        self.sink = sink_index
        self.proplist = {
            'application.name': app_name,
            'application.process.binary': app_name.lower(),
            'application.process.id': '1234',
        }


class FakeServerInfo:
    default_sink_name = PULSE_GAME_NODE_NAME


class FakePulse:
    moved_stream = None

    def sink_list(self):
        return [
            FakeSink(PULSE_GAME_NODE_NAME, 'Arctis Game', 10),
            FakeSink(PULSE_CHAT_NODE_NAME, 'Arctis Chat', 11),
        ]

    def server_info(self):
        return FakeServerInfo()

    def sink_input_list(self):
        return [
            FakeSinkInput(55, 10, 'Firefox'),
            FakeSinkInput(56, 99, 'Music'),
        ]

    def sink_input_move(self, stream_index, sink_index):
        self.moved_stream = (stream_index, sink_index)


def test_virtual_endpoint_statuses_report_present_missing_and_default_outputs():
    manager = object.__new__(PulseAudioManager)
    manager.pulse = FakePulse()
    manager.logger = logging.getLogger('test')

    statuses = manager.virtual_endpoint_statuses()
    by_node = {status['node_name']: status for status in statuses}

    assert by_node[PULSE_GAME_NODE_NAME]['present'] is True
    assert by_node[PULSE_GAME_NODE_NAME]['default'] is True
    assert by_node[PULSE_GAME_NODE_NAME]['description'] == 'Arctis Game'
    assert by_node[PULSE_CHAT_NODE_NAME]['present'] is True
    assert by_node[PULSE_CHAT_NODE_NAME]['default'] is False
    assert by_node[PULSE_MEDIA_NODE_NAME]['present'] is False
    assert by_node[PULSE_MICROPHONE_NODE_NAME]['implemented'] is False
    assert by_node[PULSE_MICROPHONE_NODE_NAME]['present'] is False


def test_application_routes_report_active_streams_and_current_endpoint():
    manager = object.__new__(PulseAudioManager)
    manager.pulse = FakePulse()
    manager.logger = logging.getLogger('test')

    routes = manager.application_routes()
    by_app = {route['application_name']: route for route in routes}

    assert by_app['Firefox']['stream_index'] == 55
    assert by_app['Firefox']['sink_node_name'] == PULSE_GAME_NODE_NAME
    assert by_app['Firefox']['current_endpoint_label'] == 'Game'
    assert by_app['Firefox']['routable'] is True
    assert by_app['Music']['sink_node_name'] == ''
    assert by_app['Music']['current_endpoint_label'] == ''


def test_move_application_route_uses_virtual_sink_index():
    manager = object.__new__(PulseAudioManager)
    manager.pulse = FakePulse()
    manager.logger = logging.getLogger('test')

    assert manager.move_application_route(55, PULSE_CHAT_NODE_NAME) is True
    assert manager.pulse.moved_stream == (55, 11)


def test_move_application_route_rejects_unknown_endpoint():
    manager = object.__new__(PulseAudioManager)
    manager.pulse = FakePulse()
    manager.logger = logging.getLogger('test')

    assert manager.move_application_route(55, 'Not_An_Endpoint') is False
    assert manager.pulse.moved_stream is None


class FakeModule:
    def __init__(self, index: int, name: str, argument: str):
        self.index = index
        self.name = name
        self.argument = argument


class FakeModulePulse:
    """Simulates the PulseAudio module and sink state relevant to virtual sinks."""

    def __init__(self, modules: list[FakeModule] | None = None):
        self.modules = list(modules or [])
        self.loaded: list[tuple[str, str]] = []
        self.unloaded: list[int] = []

    def module_list(self):
        return list(self.modules)

    def module_load(self, name: str, args: str):
        self.loaded.append((name, args))
        self.modules.append(FakeModule(100 + len(self.loaded), name, args))

    def module_unload(self, index: int):
        self.unloaded.append(index)
        self.modules = [m for m in self.modules if m.index != index]

    def sink_list(self):
        return [
            FakeSink(arg.split('=', 1)[1], '', module.index)
            for module in self.modules
            if module.name in ('module-null-sink', 'module-remap-sink')
            for arg in module.argument.split()
            if arg.startswith('sink_name=')
        ]


def make_module_manager(pulse: FakeModulePulse) -> PulseAudioManager:
    manager = object.__new__(PulseAudioManager)
    manager.pulse = pulse
    manager.logger = logging.getLogger('test')
    return manager


def test_create_virtual_sink_loads_a_single_remap_sink():
    pulse = FakeModulePulse()
    manager = make_module_manager(pulse)

    manager.create_virtual_sink(PULSE_GAME_NODE_NAME, 'Arctis Nova Game', 'alsa_output.headset')

    assert pulse.loaded == [(
        'module-remap-sink',
        f'sink_name={PULSE_GAME_NODE_NAME} '
        'sink_properties=node.description="Arctis\\ Nova\\ Game" '
        'master=alsa_output.headset',
    )]


def test_create_virtual_sink_keeps_existing_remap_sink():
    pulse = FakeModulePulse([
        FakeModule(1, 'module-remap-sink', f'sink_name={PULSE_GAME_NODE_NAME} master=alsa_output.headset'),
    ])
    manager = make_module_manager(pulse)

    manager.create_virtual_sink(PULSE_GAME_NODE_NAME, 'Game', 'alsa_output.headset')

    assert pulse.loaded == []
    assert pulse.unloaded == []


def test_create_virtual_sink_replaces_legacy_null_sink_and_loopback():
    pulse = FakeModulePulse([
        FakeModule(1, 'module-null-sink', f'sink_name={PULSE_GAME_NODE_NAME} sink_properties=node.description="Game"'),
        FakeModule(2, 'module-loopback', f'source={PULSE_GAME_NODE_NAME}.monitor sink=alsa_output.headset latency_msec=0'),
        FakeModule(3, 'module-null-sink', f'sink_name={PULSE_CHAT_NODE_NAME}'),
    ])
    manager = make_module_manager(pulse)

    manager.create_virtual_sink(PULSE_GAME_NODE_NAME, 'Game', 'alsa_output.headset')

    assert sorted(pulse.unloaded) == [1, 2]
    assert [name for name, _ in pulse.loaded] == ['module-remap-sink']
    assert {m.name for m in pulse.modules} == {'module-null-sink', 'module-remap-sink'}


def test_remove_virtual_sink_unloads_remap_sink():
    pulse = FakeModulePulse([
        FakeModule(1, 'module-remap-sink', f'sink_name={PULSE_GAME_NODE_NAME} master=alsa_output.headset'),
        FakeModule(2, 'module-remap-sink', f'sink_name={PULSE_CHAT_NODE_NAME} master=alsa_output.headset'),
    ])
    manager = make_module_manager(pulse)

    manager.remove_virtual_sink(PULSE_GAME_NODE_NAME)

    assert pulse.unloaded == [1]


class FakeVolumePulse:
    def __init__(self):
        self.volumes: dict[str, float] = {}

    def volume_set_all_chans(self, sink, volume):
        self.volumes[sink.proplist['node.name']] = volume


def _volume_manager():
    manager = object.__new__(PulseAudioManager)
    manager.pulse = FakeVolumePulse()
    manager.logger = logging.getLogger('test')
    manager.get_arctis_sinks = lambda *args, **kwargs: [
        FakeSink(PULSE_GAME_NODE_NAME, 'Arctis Game', 10),
        FakeSink(PULSE_CHAT_NODE_NAME, 'Arctis Chat', 11),
        FakeSink(PULSE_MEDIA_NODE_NAME, 'Arctis Media', 12),
        FakeSink(PULSE_AUX_NODE_NAME, 'Arctis Aux', 13),
    ]
    return manager


def test_set_mix_uses_default_mix_groups():
    manager = _volume_manager()

    manager.set_mix(30, 80)

    assert manager.pulse.volumes == {
        PULSE_GAME_NODE_NAME: 0.3,
        PULSE_CHAT_NODE_NAME: 0.8,
        PULSE_MEDIA_NODE_NAME: 0.3,
        PULSE_AUX_NODE_NAME: 0.3,
    }


def test_set_mix_honors_custom_mix_groups():
    manager = _volume_manager()

    manager.set_mix(30, 80, {'aux': 'chat', 'chat': 'media'})

    assert manager.pulse.volumes == {
        PULSE_GAME_NODE_NAME: 0.3,
        PULSE_CHAT_NODE_NAME: 0.3,
        PULSE_MEDIA_NODE_NAME: 0.3,
        PULSE_AUX_NODE_NAME: 0.8,
    }


def test_virtual_endpoint_statuses_report_custom_mix_groups():
    manager = object.__new__(PulseAudioManager)
    manager.pulse = FakePulse()
    manager.logger = logging.getLogger('test')

    by_node = {status['node_name']: status for status in manager.virtual_endpoint_statuses({'aux': 'chat'})}

    assert by_node[PULSE_AUX_NODE_NAME]['mix_group'] == 'chat'
    assert by_node[PULSE_GAME_NODE_NAME]['mix_group'] == 'media'
    assert by_node[PULSE_MICROPHONE_NODE_NAME]['mix_group'] == 'microphone'
