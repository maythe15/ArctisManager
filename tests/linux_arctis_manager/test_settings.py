from linux_arctis_manager import settings as settings_module
from linux_arctis_manager.settings import GeneralSettings


def test_general_settings_default_to_hardware_chatmix_groups():
    general = GeneralSettings()

    assert general.mix_groups == {
        'game': 'media',
        'chat': 'chat',
        'media': 'media',
        'aux': 'media',
    }


def test_mix_groups_are_kept_out_of_the_generic_general_payload():
    assert 'mix_groups' not in GeneralSettings().to_dict()


def test_set_mix_group_rejects_unknown_channels_and_groups():
    general = GeneralSettings()

    assert general.set_mix_group('aux', 'chat') is True
    assert general.mix_groups['aux'] == 'chat'
    assert general.set_mix_group('microphone', 'chat') is False
    assert general.set_mix_group('game', 'microphone') is False
    assert general.mix_groups['game'] == 'media'


def test_mix_groups_round_trip_through_general_settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, 'SETTINGS_FOLDER', tmp_path)

    general = GeneralSettings()
    general.set_mix_group('aux', 'chat')
    general.set_mix_group('chat', 'media')
    general.write_to_file()

    loaded = GeneralSettings.read_from_file()

    assert loaded.mix_groups == {
        'game': 'media',
        'chat': 'media',
        'media': 'media',
        'aux': 'chat',
    }


def test_invalid_mix_groups_in_file_fall_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, 'SETTINGS_FOLDER', tmp_path)
    (tmp_path / 'general_settings.yaml').write_text(
        'mix_groups:\n  aux: chat\n  game: nowhere\n  bogus: chat\n',
        encoding='utf-8',
    )

    loaded = GeneralSettings.read_from_file()

    assert loaded.mix_groups == {
        'game': 'media',
        'chat': 'chat',
        'media': 'media',
        'aux': 'chat',
    }
