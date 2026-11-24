import asyncio
import logging
import os
from threading import Event

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLabel,
                               QPushButton, QSlider, QWidget)

import linux_arctis_manager.gui.dbus_wrapper as dbus_wrapper_module
from linux_arctis_manager.gui.dbus_wrapper import DbusWrapper
from linux_arctis_manager.gui.main_app import QMainApp
from linux_arctis_manager.gui.ui_utils import install_pointing_cursor_filter


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def _routing_settings(*stream_indexes: int) -> dict:
    return {
        'audio_endpoints': [
            {'node_name': node, 'label': label, 'kind': 'sink', 'mix_group': 'media',
             'implemented': True, 'present': True, 'default': False, 'description': label}
            for node, label in [('Arctis_Game', 'Game'), ('Arctis_Chat', 'Chat')]
        ],
        'application_routes': [
            {'stream_index': index, 'name': f'App {index}', 'application_name': f'App {index}',
             'current_endpoint_label': 'Game', 'current_endpoint_node_name': 'Arctis_Game'}
            for index in stream_indexes
        ],
    }


class FakeBus:
    instances: list['FakeBus'] = []

    def __init__(self):
        self.loop = None
        self.disconnected = False
        self.moves: list[tuple[int, str]] = []
        self.mix_groups: list[tuple[str, str]] = []
        self.set_settings: list[tuple[str, str]] = []
        FakeBus.instances.append(self)

    @property
    def connected(self):
        return self.loop is not None and not self.disconnected

    async def connect(self):
        self.loop = asyncio.get_running_loop()
        return self

    def _check_loop(self):
        # A real dbus-next bus only works on the loop that created it.
        assert asyncio.get_running_loop() is self.loop

    async def introspect(self, *_):
        self._check_loop()
        return None

    def get_proxy_object(self, *_):
        return self

    def get_interface(self, _name):
        return self

    async def call(self, message):
        self._check_loop()
        self.set_settings.append(tuple(message.body))
        return None

    async def call_move_application_route(self, stream_index, endpoint_node_name):
        self._check_loop()
        self.moves.append((stream_index, endpoint_node_name))
        return True

    async def call_set_mix_group(self, channel, group):
        self._check_loop()
        self.mix_groups.append((channel, group))
        return True

    async def call_get_settings(self):
        self._check_loop()
        return '{}'

    def disconnect(self):
        self.disconnected = True


@pytest.fixture
def fake_bus(monkeypatch):
    FakeBus.instances = []
    monkeypatch.setattr(dbus_wrapper_module, 'MessageBus', FakeBus)
    monkeypatch.setattr(DbusWrapper, '_bus', None)
    monkeypatch.setattr(DbusWrapper, '_interfaces', {})
    return FakeBus


def _drain_dbus_loop() -> None:
    '''Wait until every request queued so far on the shared D-Bus loop has run.'''
    async def noop() -> None:
        return None

    asyncio.run_coroutine_threadsafe(noop(), DbusWrapper._get_loop()).result(5)


def test_move_application_route_reuses_one_bus(fake_bus):
    _app()
    wrapper = DbusWrapper()
    results = []
    done = Event()

    def on_moved(success, stream_index, endpoint):
        results.append((success, stream_index, endpoint))
        done.set()

    wrapper.sig_route_moved.connect(on_moved, Qt.ConnectionType.DirectConnection)

    wrapper.move_application_route(55, 'Arctis_Chat')
    assert done.wait(5)
    done.clear()
    wrapper.move_application_route(56, 'Arctis_Game')
    assert done.wait(5)
    _drain_dbus_loop()

    assert results == [(True, 55, 'Arctis_Chat'), (True, 56, 'Arctis_Game')]
    assert len(fake_bus.instances) == 1
    assert fake_bus.instances[0].moves == [(55, 'Arctis_Chat'), (56, 'Arctis_Game')]


def test_set_mix_group_uses_the_shared_bus(fake_bus):
    _app()
    wrapper = DbusWrapper()
    settings_received = Event()
    wrapper.sig_settings.connect(lambda _: settings_received.set(), Qt.ConnectionType.DirectConnection)

    wrapper.set_mix_group('aux', 'chat')
    assert settings_received.wait(5)

    assert len(fake_bus.instances) == 1
    assert fake_bus.instances[0].mix_groups == [('aux', 'chat')]


def test_slider_burst_of_set_setting_uses_one_connection_in_order(fake_bus):
    # Dragging a slider sends one SetSetting per tick; this used to open (and leak)
    # a connection per call until the GUI hit "too many open files".
    for value in range(200):
        DbusWrapper.change_setting('eq_band_1', value)
    _drain_dbus_loop()

    assert len(fake_bus.instances) == 1
    assert fake_bus.instances[0].set_settings == [('eq_band_1', str(value)) for value in range(200)]


def test_dropped_bus_is_replaced(fake_bus):
    DbusWrapper.change_setting('gain', 1)
    _drain_dbus_loop()
    fake_bus.instances[0].disconnected = True

    DbusWrapper.change_setting('gain', 2)
    _drain_dbus_loop()

    assert len(fake_bus.instances) == 2
    assert fake_bus.instances[1].set_settings == [('gain', '2')]


def test_route_move_feedback_survives_settings_refresh():
    app = _app()
    window_app = QMainApp(app, logging.CRITICAL, demo_mode=True)

    class FakeDbusWrapper:
        moved_route = None

        def move_application_route(self, stream_index, endpoint_node_name):
            self.moved_route = (stream_index, endpoint_node_name)

        def stop(self):
            pass

    fake_dbus = FakeDbusWrapper()
    window_app.dbus_wrapper = fake_dbus  # type: ignore[assignment]
    window_app.on_settings_received(_routing_settings(55, 56))

    window_app.route_app_stream_combo.setCurrentIndex(window_app.route_app_stream_combo.findData(56))
    window_app.route_endpoint_combo.setCurrentIndex(window_app.route_endpoint_combo.findData('Arctis_Chat'))
    window_app._on_assign_route_clicked()
    assert fake_dbus.moved_route == (56, 'Arctis_Chat')

    window_app.on_route_moved(True, 56, 'Arctis_Chat')
    assert window_app.application_route_status_label.text() == 'Moved App 56 to Chat.'

    # A settings refresh must neither reset the picks nor wipe the feedback.
    refreshed = _routing_settings(55, 56)
    refreshed['application_routes'][1]['current_endpoint_label'] = 'Chat'
    window_app.on_settings_received(refreshed)
    assert window_app.route_app_stream_combo.currentData() == 56
    assert window_app.route_endpoint_combo.currentData() == 'Arctis_Chat'
    assert window_app.application_route_status_label.text() == (
        'Moved App 56 to Chat. 2 active app stream(s) can be assigned.'
    )

    window_app.on_route_moved(False, 55, 'Arctis_Game')
    assert window_app.application_route_status_label.text().startswith('Could not move App 55 to Game')

    window_app.sig_stop()


def test_pointing_cursor_filter_marks_enabled_clickable_widgets():
    app = _app()
    install_pointing_cursor_filter(app)

    container = QWidget()
    button = QPushButton('Go', container)
    combo = QComboBox(container)
    slider = QSlider(container)
    checkbox = QCheckBox('Check', container)
    label = QLabel('Text', container)
    container.show()
    app.processEvents()

    for widget in (button, combo, slider, checkbox):
        assert widget.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert label.cursor().shape() == Qt.CursorShape.ArrowCursor

    button.setEnabled(False)
    app.processEvents()
    assert button.cursor().shape() == Qt.CursorShape.ArrowCursor

    button.setEnabled(True)
    app.processEvents()
    assert button.cursor().shape() == Qt.CursorShape.PointingHandCursor

    container.close()
