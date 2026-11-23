import logging

from linux_arctis_manager.core import CoreEngine
from linux_arctis_manager.settings import GeneralSettings


class FakeAudioManager:
    def __init__(self):
        self.calls: list[tuple[int, int, dict[str, str]]] = []

    def set_mix(self, media_mix, chat_mix, mix_groups=None):
        self.calls.append((media_mix, chat_mix, dict(mix_groups or {})))


def _core(device_status: dict | None) -> CoreEngine:
    core = object.__new__(CoreEngine)
    core.logger = logging.getLogger('test')
    core.general_settings = GeneralSettings()
    core.general_settings.write_to_file = lambda: None
    core.pa_audio_manager = FakeAudioManager()  # pyright: ignore[reportAttributeAccessIssue]
    core.device_status = device_status  # pyright: ignore[reportAttributeAccessIssue]
    core.media_mix = 40
    core.chat_mix = 90
    return core


def test_set_mix_group_reapplies_current_chatmix():
    core = _core({'media_mix': 1, 'chat_mix': 2})

    assert core.set_mix_group('aux', 'chat') is True

    assert core.general_settings.mix_groups['aux'] == 'chat'
    assert core.pa_audio_manager.calls == [  # pyright: ignore[reportAttributeAccessIssue]
        (40, 90, {'game': 'media', 'chat': 'chat', 'media': 'media', 'aux': 'chat'}),
    ]


def test_set_mix_group_leaves_volumes_alone_without_chatmix_status():
    core = _core({'battery': 3})

    assert core.set_mix_group('aux', 'chat') is True

    assert core.general_settings.mix_groups['aux'] == 'chat'
    assert core.pa_audio_manager.calls == []  # pyright: ignore[reportAttributeAccessIssue]


def test_set_mix_group_rejects_invalid_assignment():
    core = _core({'media_mix': 1, 'chat_mix': 2})

    assert core.set_mix_group('microphone', 'chat') is False
    assert core.pa_audio_manager.calls == []  # pyright: ignore[reportAttributeAccessIssue]
