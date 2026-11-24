import logging
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from linux_arctis_manager.config import ConfigSettingFeedback, DeviceConfiguration
from linux_arctis_manager.core import CoreEngine
from linux_arctis_manager.settings import DeviceSettings

DEVICES = Path(__file__).parents[2] / 'src' / 'linux_arctis_manager' / 'devices'


def _pad(*data: int) -> list[int]:
    return [*data] + [0] * (64 - len(data))


# Captured from a real Nova Pro Wireless while changing the EQ on the base station
STATION_STATUS = _pad(6, 176, 0, 0, 1, 0, 5, 0, 10, 0, 1, 10, 5, 0, 8, 8)
STATION_PRESET_CUSTOM = _pad(7, 46, 4)
STATION_BAND_3_TO_40 = _pad(7, 49, 3, 40)
STATION_BAND_3_TO_0 = _pad(7, 49, 3, 0)


def _nova_pro_wireless() -> DeviceConfiguration:
    return DeviceConfiguration(YAML(typ='safe').load(DEVICES / 'nova_pro_wireless.yaml'))


def _core(tmp_path, monkeypatch) -> tuple[CoreEngine, list[list[int]], list[DeviceSettings]]:
    monkeypatch.setattr('linux_arctis_manager.settings.SETTINGS_FOLDER', tmp_path)
    config = _nova_pro_wireless()
    sent: list[list[int]] = []
    notified: list[DeviceSettings] = []

    core = object.__new__(CoreEngine)
    core.logger = logging.getLogger('test')
    core.device_config = config
    core.device_settings_observers = []
    core.device_settings = DeviceSettings(0x1038, 0x12e0)
    for section in config.settings.values():
        for setting in section:
            setattr(core.device_settings, setting.name, setting.default_value)
    # Changing a setting from the app sends it to the device; feedback must not.
    core.device_settings.settings.add_observer(lambda name, value: sent.append([name, value]))  # type: ignore[list-item]
    core.register_settings_observer(notified.append)
    return core, sent, notified


def test_nova_pro_wireless_follows_eq_changes_made_on_the_station(tmp_path, monkeypatch):
    core, sent, notified = _core(tmp_path, monkeypatch)

    for packet in (STATION_STATUS, STATION_PRESET_CUSTOM, STATION_BAND_3_TO_40):
        core.apply_settings_feedback(packet)

    assert core.device_settings.get('eq_preset') == 4
    assert core.device_settings.get('eq_band_3') == 40
    assert core.device_settings.get('eq_band_2') == 0x14
    assert sent == []  # nothing echoed back to the station
    assert len(notified) == 2
    saved = YAML(typ='safe').load(tmp_path / '1038_12e0.yaml')
    assert saved['eq_preset'] == 4 and saved['eq_band_3'] == 40


def test_unchanged_value_does_not_notify(tmp_path, monkeypatch):
    core, _, notified = _core(tmp_path, monkeypatch)

    core.apply_settings_feedback(STATION_BAND_3_TO_0)
    core.apply_settings_feedback(STATION_BAND_3_TO_0)

    assert core.device_settings.get('eq_band_3') == 0
    assert len(notified) == 1


def test_feedback_selector_out_of_range_is_ignored():
    feedback = ConfigSettingFeedback(starts_with=0x0731, value_index=3, setting_index=2,
                                     settings=['a', 'b'])
    assert feedback.match(_pad(7, 49, 1, 5)) == ('a', 5)
    assert feedback.match(_pad(7, 49, 0, 5)) is None
    assert feedback.match(_pad(7, 49, 3, 5)) is None
    assert feedback.match(_pad(7, 46, 1, 5)) is None


def test_feedback_entry_requires_a_target():
    with pytest.raises(ValueError):
        ConfigSettingFeedback(starts_with=0x0731, value_index=3)
