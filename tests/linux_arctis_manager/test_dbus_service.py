import json
from types import SimpleNamespace

from linux_arctis_manager.dbus_service import ArctisManagerDbusSettingsService


def test_settings_payload_includes_connected_device_identity():
    core = SimpleNamespace(
        device_config=SimpleNamespace(name='SteelSeries Arctis Nova 7', settings={}),
        usb_device=SimpleNamespace(idVendor=0x1038, idProduct=0x2202),
        general_settings=SimpleNamespace(settings_config=[], to_dict=lambda: {}),
        device_settings=SimpleNamespace(settings={}),
        pa_audio_manager=SimpleNamespace(),
        register_settings_observer=lambda _observer: None,
    )
    service = ArctisManagerDbusSettingsService(core)
    service._profile_metadata = lambda: {'available': [], 'active': 'Default'}
    service._audio_endpoint_metadata = lambda: []
    service._application_route_metadata = lambda: []

    payload = json.loads(service.settings_to_json(
        core.general_settings,
        core.device_config,
        core.device_settings,
    ))

    assert payload['device_info'] == {
        'name': 'SteelSeries Arctis Nova 7',
        'vendor_id': '1038',
        'product_id': '2202',
    }
    assert payload['mix_groups'] == {
        'game': 'media',
        'chat': 'chat',
        'media': 'media',
        'aux': 'media',
    }


def set_mix_group(service: ArctisManagerDbusSettingsService, channel: str, group: str):
    # dbus-next's @method wrapper drops return values; call the undecorated function.
    return ArctisManagerDbusSettingsService.set_mix_group.__wrapped__(service, channel, group)  # pyright: ignore[reportFunctionMemberAccess]


def _mix_group_service(set_mix_group_result: bool):
    calls = []
    general_settings = SimpleNamespace(
        settings_config=[],
        to_dict=lambda: {},
        mix_groups={'game': 'media', 'chat': 'chat', 'media': 'media', 'aux': 'media'},
    )

    def set_mix_group(channel, group):
        calls.append((channel, group))
        if set_mix_group_result:
            general_settings.mix_groups = {**general_settings.mix_groups, channel: group}
        return set_mix_group_result

    core = SimpleNamespace(
        device_config=None,
        usb_device=None,
        general_settings=general_settings,
        device_settings=None,
        pa_audio_manager=SimpleNamespace(),
        register_settings_observer=lambda _observer: None,
        set_mix_group=set_mix_group,
    )
    service = ArctisManagerDbusSettingsService(core)
    service._profile_metadata = lambda: {'available': [], 'active': 'Default'}
    service._audio_endpoint_metadata = lambda: []
    service._application_route_metadata = lambda: []
    emitted = []
    service.signal_settings_changed = lambda payload: emitted.append(json.loads(payload))

    return service, calls, emitted


def test_set_mix_group_updates_core_and_emits_settings():
    service, calls, emitted = _mix_group_service(True)

    assert set_mix_group(service, 'aux', 'chat') is True

    assert calls == [('aux', 'chat')]
    assert len(emitted) == 1
    assert emitted[0]['mix_groups']['aux'] == 'chat'


def test_set_mix_group_rejection_does_not_emit_settings():
    service, calls, emitted = _mix_group_service(False)

    assert set_mix_group(service, 'microphone', 'chat') is False

    assert calls == [('microphone', 'chat')]
    assert emitted == []
