import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from linux_arctis_manager.gui.settings_widget import QSettingsWidget
from linux_arctis_manager.gui.status_widget import QStatusWidget


def _app():
    return QApplication.instance() or QApplication([])


def test_status_widget_renders_dbus_status_payload():
    app = _app()
    widget = QStatusWidget(None)
    widget.update_status({
        'headset': {
            'headset_power_status': {'value': 'online', 'type': 'label'},
            'headset_battery_charge': {'value': 87, 'type': 'percentage'},
        },
    })
    app.processEvents()

    labels = [label.text() for label in widget.findChildren(QLabel)]

    assert 'Headset' in labels
    assert 'Headset Power Status' in labels
    assert 'Online' in labels
    assert 'Headset Battery Charge' in labels
    assert '87%' in labels
    assert len(widget.findChildren(QWidget, 'statusGroup')) == 1


def test_settings_widget_renders_dbus_settings_metadata():
    app = _app()
    widget = QSettingsWidget(None, 'general', 'general')
    widget.update_settings({
        'general': {
            'redirect_audio_on_connect': True,
            'volume_preview': 7,
        },
        'settings_config': {
            'redirect_audio_on_connect': {
                'type': 'toggle',
                'default_value': False,
                'values': {
                    'on': True,
                    'off': False,
                    'off_label': 'off',
                    'on_label': 'on',
                },
            },
            'volume_preview': {
                'type': 'slider',
                'default_value': 5,
                'min': 0,
                'max': 10,
                'step': 1,
            },
        },
    })
    app.processEvents()

    labels = [label.text() for label in widget.findChildren(QLabel)]

    assert 'General' in labels
    assert 'Redirect Audio on Connect' in labels
    assert 'volume_preview' in labels
    assert len(widget.findChildren(QWidget, 'settingRow')) == 2


def test_setting_controls_use_the_app_styles():
    from PySide6.QtWidgets import QPushButton

    from linux_arctis_manager.gui.qt_widgets.q_checkable_button_group import \
        QCheckableButtonGroup
    from linux_arctis_manager.gui.qt_widgets.q_toggle import (KNOB,
                                                              LEFT_MARGIN,
                                                              QToggle)

    _app()
    group = QCheckableButtonGroup()
    group.addButton(value=0, label='low', selected=False)
    group.addButton(value=1, label='high', selected=True)
    buttons = group.findChildren(QPushButton)
    assert [button.objectName() for button in buttons] == ['optionChip', 'optionChip']
    assert group.styleSheet() == ''

    toggle = QToggle()
    toggle.setChecked(True)
    # Initial state is drawn at once, not animated from the off position.
    assert toggle.circle_position == toggle.width() - LEFT_MARGIN - KNOB
