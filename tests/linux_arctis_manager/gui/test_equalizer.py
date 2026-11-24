import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from ruamel.yaml import YAML

from linux_arctis_manager.config import DeviceConfiguration
from linux_arctis_manager.dbus_service import ArctisManagerDbusSettingsService
from linux_arctis_manager.gui.view_models import (equalizer_model,
                                                  is_equalizer_band,
                                                  is_equalizer_setting)

DEVICES_DIR = Path(__file__).parents[3] / 'src' / 'linux_arctis_manager' / 'devices'


def _payload(device_file: str, overrides: dict | None = None) -> dict:
    '''Settings payload as the daemon sends it over D-Bus, for a bundled device YAML.'''
    device_config = DeviceConfiguration(YAML(typ='safe').load(DEVICES_DIR / device_file))
    device_settings = SimpleNamespace(settings={
        config.name: config.default_value
        for configs in device_config.settings.values()
        for config in configs
    } | (overrides or {}))
    core = SimpleNamespace(
        device_config=device_config,
        usb_device=SimpleNamespace(idVendor=device_config.vendor_id, idProduct=device_config.product_ids[0]),
        general_settings=SimpleNamespace(settings_config=[], to_dict=lambda: {}),
        device_settings=device_settings,
        pa_audio_manager=SimpleNamespace(),
        register_settings_observer=lambda _observer: None,
    )
    service = ArctisManagerDbusSettingsService(core)
    service._profile_metadata = lambda: {'available': [], 'active': 'Default'}
    service._audio_endpoint_metadata = lambda: []
    service._application_route_metadata = lambda: []

    return json.loads(service.settings_to_json(core.general_settings, device_config, device_settings))


def test_settings_config_carries_the_yaml_section():
    config = _payload('nova_pro_wireless.yaml')['settings_config']

    assert config['eq_preset']['section'] == 'equalizer'
    assert config['eq_band_1']['section'] == 'equalizer'
    assert config['mic_volume']['section'] == 'microphone'
    assert is_equalizer_setting(config['eq_preset']) and not is_equalizer_band(config['eq_preset'])
    assert is_equalizer_band(config['eq_band_10'])
    assert not is_equalizer_setting(config['mic_volume'])


def test_equalizer_model_for_nova_pro_wireless():
    model = equalizer_model(_payload('nova_pro_wireless.yaml', {
        'eq_preset': 0x04, 'eq_band_1': 0x1e, 'eq_band_10': 0x00,
    }))

    assert model['available'] is True
    assert model['empty_message'] == ''
    assert model['controls'] == []
    assert [preset['name'] for preset in model['presets']] == ['eq_preset']
    preset = model['presets'][0]
    assert [option['label'] for option in preset['options']] == ['Flat', 'Bass Boost', 'Focus', 'Smiley', 'Custom']
    assert preset['custom_value'] == 0x04
    assert preset['is_custom'] is True
    assert model['locked'] is False
    assert model['can_reset'] is True
    assert [band['label'] for band in model['bands']] == [
        '32 Hz', '64 Hz', '125 Hz', '250 Hz', '500 Hz', '1 kHz', '2 kHz', '4 kHz', '8 kHz', '16 kHz',
    ]
    assert model['bands'][0]['value'] == 0x1e
    assert model['bands'][0]['value_label'] == '+5 dB'
    assert model['bands'][1]['value_label'] == '0 dB'
    assert model['bands'][9]['value_label'] == '-10 dB'
    assert model['bands'][0]['value_labels'][0x15] == '+0.5 dB'
    assert model['bands'][0]['default'] == 0x14
    assert [tick['label'] for tick in model['scale']] == ['-10 dB', '-5 dB', '0 dB', '+5 dB', '+10 dB']
    assert model['baseline'] == 0x14
    assert model['hint'] == ''


def test_equalizer_model_shows_and_locks_a_fixed_preset_curve():
    # Custom band values are stored, but Bass Boost is active: the graph shows the preset curve
    model = equalizer_model(_payload('nova_pro_wireless.yaml', {'eq_preset': 0x01, 'eq_band_1': 0x00}))

    assert model['locked'] is True
    assert model['can_reset'] is False
    assert [band['value'] for band in model['bands']] == [0x1b, 0x1f, 0x1c, 0x16, 0x11, 0x11, 0x12, 0x12, 0x12, 0x12]
    assert model['bands'][1]['value_label'] == '+5.5 dB'
    assert model['hint'] == 'Bass Boost is a fixed preset. Select Custom to adjust the bands.'

    flat = equalizer_model(_payload('nova_pro_wireless.yaml', {'eq_preset': 0x00, 'eq_band_1': 0x00}))
    assert flat['locked'] is True
    assert {band['value'] for band in flat['bands']} == {0x14}


def test_equalizer_model_locks_a_preset_without_a_known_curve():
    payload = _payload('nova_pro_wireless.yaml', {'eq_preset': 0x02, 'eq_band_1': 0x00})
    del payload['settings_config']['eq_preset']['preset_bands']
    model = equalizer_model(payload)

    assert model['locked'] is True
    assert model['bands'][0]['value'] == 0x00  # the stored Custom values
    assert model['hint'].startswith('Focus is a fixed preset; its curve is not known')


def test_equalizer_model_preset_only_device():
    model = equalizer_model(_payload('nova_elite.yaml'))

    assert model['available'] is True
    assert model['bands'] == []
    assert model['hint'] == ''
    assert model['locked'] is False
    assert [preset['name'] for preset in model['presets']] == ['equalizer_wireless', 'equalizer_bluetooth']
    assert model['presets'][0]['options'][1]['label'] == 'Bass boost'


def test_equalizer_model_without_equalizer():
    assert equalizer_model({})['empty_message'] == 'Connect a supported headset to show its equalizer.'
    assert equalizer_model({})['available'] is False

    model = equalizer_model(_payload('nova_7_wireless_perc_battery.yaml'))
    assert model['available'] is False
    assert model['empty_message'] == 'The connected headset does not expose equalizer controls.'


def test_equalizer_model_without_value_labels_uses_midpoint_and_numbers():
    settings = {
        'device': {'band_a': 3, 'band_b': 99},
        'settings_config': {
            'band_a': {'type': 'slider', 'section': 'equalizer', 'min': 0, 'max': 6, 'step': 1},
            'band_b': {'type': 'slider', 'section': 'equalizer_mic', 'min': 0, 'max': 6, 'step': 1},
        },
    }
    model = equalizer_model(settings)

    assert [band['label'] for band in model['bands']] == ['1', '2']
    assert model['bands'][1]['value'] == 6  # clamped
    assert model['baseline'] == 3
    assert [tick['value'] for tick in model['scale']] == [0, 2, 3, 4, 6]


# ----- widgets -----

QtWidgets = pytest.importorskip('PySide6.QtWidgets')

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_equalizer_graph_commits_keyboard_and_mouse_changes():
    from linux_arctis_manager.gui.qt_widgets.q_equalizer import QEqualizerGraph

    app = _app()
    model = equalizer_model(_payload('nova_pro_wireless.yaml'))
    graph = QEqualizerGraph()
    graph.resize(720, 300)
    graph.set_bands(model['bands'], model['scale'], model['baseline'])
    graph.show()
    app.processEvents()

    emitted: list[tuple[str, int]] = []
    graph.band_changed.connect(lambda name, value: emitted.append((name, value)))

    graph.setFocus()
    QTest.keyClick(graph, Qt.Key.Key_Right)
    QTest.keyClick(graph, Qt.Key.Key_Up)
    QTest.keyClick(graph, Qt.Key.Key_Up)
    assert graph.selected_band() == 1
    assert graph.bands()[1]['value_label'] == '+1 dB'
    assert emitted == []  # debounced
    graph._commit_timer.timeout.emit()
    assert emitted == [('eq_band_2', 0x16)]

    # An update from the daemon while nothing is pending replaces the local values
    graph.set_bands(model['bands'], model['scale'], model['baseline'])
    assert graph.bands()[1]['value'] == 0x14

    # Drag the last band to the top of the plot: one commit on release, at the maximum
    emitted.clear()
    x = int(graph._band_x(9))
    QTest.mousePress(graph, Qt.MouseButton.LeftButton, pos=QPoint(x, int(graph._plot_rect().center().y())))
    QTest.mouseMove(graph, QPoint(x, 2))
    QTest.mouseRelease(graph, Qt.MouseButton.LeftButton, pos=QPoint(x, 2))
    assert emitted == [('eq_band_10', 0x28)]

    # Double-click resets to the band default (0 dB)
    emitted.clear()
    QTest.mouseDClick(graph, Qt.MouseButton.LeftButton, pos=QPoint(x, 2))
    assert emitted[-1] == ('eq_band_10', 0x14)

    graph.grab()  # paints without errors
    graph.close()


def test_equalizer_page_moves_eq_settings_off_the_device_page():
    from linux_arctis_manager.gui.main_app import QMainApp

    app = _app()
    window_app = QMainApp(app, logging.CRITICAL, demo_mode=True)
    window_app.switch_panel('equalizer')
    window_app.main_window.show()
    app.processEvents()

    assert window_app.header_title.text() == 'Equalizer'
    assert window_app.nav_buttons['equalizer'].isChecked()
    # Demo device has no EQ
    assert window_app.equalizer_empty_label.isVisibleTo(window_app.main_window)
    assert not window_app.equalizer_bands_card.isVisibleTo(window_app.main_window)

    window_app.on_settings_received(_payload('nova_pro_wireless.yaml'))
    app.processEvents()

    visible = lambda widget: widget.isVisibleTo(window_app.main_window)  # noqa: E731
    assert not visible(window_app.equalizer_empty_label)
    assert visible(window_app.equalizer_presets_card)
    assert not visible(window_app.equalizer_controls_card)  # the preset is shown as chips instead
    assert visible(window_app.equalizer_bands_card)
    assert window_app.equalizer_controls_widget.settings == {}
    assert len(window_app.equalizer_graph.bands()) == 10

    # Default preset is Flat: chips reflect it, the graph is locked and Reset is disabled
    chips = window_app.equalizer_preset_buttons
    assert [chips[('eq_preset', value)].text() for value in range(5)] == ['Flat', 'Bass Boost', 'Focus', 'Smiley', 'Custom']
    assert chips[('eq_preset', 0x00)].isChecked()
    assert chips[('eq_preset', 0x00)].objectName() == 'presetChip'
    assert not window_app.equalizer_graph.isEnabled()
    assert window_app.equalizer_hint_label.text() == 'Flat is a fixed preset. Select Custom to adjust the bands.'
    assert not window_app.equalizer_flat_button.isEnabled()
    # Reset to flat sits in the Band Gains card header, beside the title
    header = window_app.equalizer_bands_card.layout().itemAt(0).layout()
    assert header is not None and header.indexOf(window_app.equalizer_flat_button) == 1

    # Choosing Bass Boost (demo mode applies changes locally) shows its curve, still locked
    chips[('eq_preset', 0x01)].click()
    assert window_app.settings['device']['eq_preset'] == 0x01
    assert chips[('eq_preset', 0x01)].isChecked() and not chips[('eq_preset', 0x00)].isChecked()
    assert window_app.equalizer_graph.bands()[1]['value_label'] == '+5.5 dB'
    assert not window_app.equalizer_graph.isEnabled()

    # Clicking the active chip keeps it selected
    chips[('eq_preset', 0x01)].click()
    assert chips[('eq_preset', 0x01)].isChecked()

    # Custom unlocks the bands, which show the stored custom values again
    chips[('eq_preset', 0x04)].click()
    assert window_app.equalizer_graph.isEnabled()
    assert window_app.equalizer_hint_label.text() == ''
    assert window_app.equalizer_graph.bands()[1]['value_label'] == '0 dB'

    window_app._on_equalizer_band_changed('eq_band_3', 0x20)
    assert window_app.settings['device']['eq_band_3'] == 0x20
    assert window_app.equalizer_graph.bands()[2]['value_label'] == '+6 dB'
    assert window_app.equalizer_flat_button.isEnabled()
    window_app._on_equalizer_flat_clicked()
    assert window_app.settings['device']['eq_band_3'] == 0x14

    window_app.main_window.grab()  # paints without errors
    window_app.main_window.close()


def test_equalizer_graph_lock_commits_pending_edits_and_ignores_input():
    from linux_arctis_manager.gui.qt_widgets.q_equalizer import QEqualizerGraph

    app = _app()
    model = equalizer_model(_payload('nova_pro_wireless.yaml', {'eq_preset': 0x04}))
    graph = QEqualizerGraph()
    graph.resize(720, 300)
    graph.set_bands(model['bands'], model['scale'], model['baseline'])
    graph.show()
    app.processEvents()

    emitted: list[tuple[str, int]] = []
    graph.band_changed.connect(lambda name, value: emitted.append((name, value)))
    graph.setFocus()
    QTest.keyClick(graph, Qt.Key.Key_Up)
    graph.set_locked(True)
    assert emitted == [('eq_band_1', 0x15)]
    assert not graph.isEnabled()

    emitted.clear()
    x = int(graph._band_x(0))
    QTest.mousePress(graph, Qt.MouseButton.LeftButton, pos=QPoint(x, 2))
    QTest.mouseRelease(graph, Qt.MouseButton.LeftButton, pos=QPoint(x, 2))
    assert emitted == []

    graph.set_locked(False)
    assert graph.isEnabled()
    graph.close()


def test_device_settings_widget_filters_out_equalizer_settings():
    from linux_arctis_manager.gui.settings_widget import QSettingsWidget

    _app()
    parent = QtWidgets.QWidget()
    widget = QSettingsWidget(parent, 'device', 'device', setting_filter=lambda config: not is_equalizer_setting(config))
    widget.update_settings(_payload('nova_pro_wireless.yaml'))

    assert 'mic_volume' in widget.settings
    assert not any(name.startswith('eq_') for name in widget.settings)
