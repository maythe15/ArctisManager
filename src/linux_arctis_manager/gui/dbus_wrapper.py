import asyncio
import json
import logging
from contextlib import asynccontextmanager
from threading import Thread
from typing import Any, AsyncIterator, Callable, Coroutine

from dbus_next.aio.message_bus import MessageBus
from dbus_next.aio.proxy_object import ProxyInterface
from dbus_next.constants import MessageType
from dbus_next.message import Message
from PySide6.QtCore import QObject, Signal, SignalInstance

from linux_arctis_manager.constants import (DBUS_BUS_NAME,
                                            DBUS_SETTINGS_INTERFACE_NAME,
                                            DBUS_SETTINGS_OBJECT_PATH,
                                            DBUS_STATUS_INTERFACE_NAME,
                                            DBUS_STATUS_OBJECT_PATH)


class DbusWrapper(QObject):
    sig_status = Signal(object)
    sig_settings = Signal(object)
    # (success, stream_index, endpoint_node_name)
    sig_route_moved = Signal(bool, int, str)

    logger = logging.getLogger('DbusWrapper')

    def __init__(self, parent: QObject|None = None):
        super().__init__(parent)

        self._stopping = False

        self._status_signal_loop: asyncio.AbstractEventLoop|None = None
        self._stop_status_signal_future: asyncio.Future|None = None

        self._settings_signal_loop: asyncio.AbstractEventLoop|None = None
        self._stop_settings_signal_future: asyncio.Future|None = None

    # A dbus-next MessageBus is bound to the asyncio loop that created it, and
    # every request here runs in its own thread with its own `asyncio.run()`
    # loop. Sharing a cached bus/interface across those loops makes calls fail
    # ("attached to a different loop" or a closed loop), so each loop gets its
    # own connection.
    @staticmethod
    @asynccontextmanager
    async def _interface(object_path: str, interface_name: str) -> AsyncIterator[ProxyInterface]:
        bus = await MessageBus().connect()
        try:
            introspection = await bus.introspect(DBUS_BUS_NAME, object_path)
            obj = bus.get_proxy_object(DBUS_BUS_NAME, object_path, introspection)
            yield obj.get_interface(interface_name)
        finally:
            bus.disconnect()

    @classmethod
    def _status_iface(cls):
        return cls._interface(DBUS_STATUS_OBJECT_PATH, DBUS_STATUS_INTERFACE_NAME)

    @classmethod
    def _settings_iface(cls):
        return cls._interface(DBUS_SETTINGS_OBJECT_PATH, DBUS_SETTINGS_INTERFACE_NAME)

    @classmethod
    def _run_in_thread(cls, description: str, coro_factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
        def target() -> None:
            try:
                asyncio.run(coro_factory())
            except Exception:
                cls.logger.exception('D-Bus request failed: %s', description)

        Thread(target=target, daemon=True).start()

    def start(self):
        self.request_status()
        self.request_settings()

        self._run_in_thread('status signal', self._register_status_dbus_signal)
        self._run_in_thread('settings signal', self._register_settings_dbus_signal)

    async def _register_status_dbus_signal(self):
        def callback(status: str) -> None:
            self.sig_status.emit(json.loads(status) or {})

        async with self._status_iface() as iface:
            iface.on_status_changed(callback) # type: ignore

            self._status_signal_loop = asyncio.get_running_loop()
            self._stop_status_signal_future = self._status_signal_loop.create_future()
            await self._stop_status_signal_future

    async def _register_settings_dbus_signal(self):
        def callback(settings: str) -> None:
            self.sig_settings.emit(json.loads(settings) or {})

        async with self._settings_iface() as iface:
            iface.on_settings_changed(callback) # type: ignore

            self._settings_signal_loop = asyncio.get_running_loop()
            self._stop_settings_signal_future = self._settings_signal_loop.create_future()
            await self._stop_settings_signal_future

    def stop(self):
        self.logger.info("Stopping D-Bus wrapper...")
        self._stopping = True
        if self._status_signal_loop and self._stop_status_signal_future:
            self._status_signal_loop.call_soon_threadsafe(self._stop_status_signal_future.set_result, None)
        if self._settings_signal_loop and self._stop_settings_signal_future:
            self._settings_signal_loop.call_soon_threadsafe(self._stop_settings_signal_future.set_result, None)

    def request_status(self) -> None:
        self._run_in_thread('GetStatus', self._request_status_async)

    async def _request_status_async(self):
        async with self._status_iface() as iface:
            result = await iface.call_get_status() # type: ignore

        self.sig_status.emit(json.loads(result) or {})

    def request_settings(self) -> None:
        self._run_in_thread('GetSettings', self._request_settings_async)

    async def _request_settings_async(self):
        async with self._settings_iface() as iface:
            result = await iface.call_get_settings() # type: ignore

        self.sig_settings.emit(json.loads(result) or {})
    
    @staticmethod
    def request_list_options(list_name: str, qt_signal: SignalInstance):
        request_thread = Thread(target=DbusWrapper.request_list_options_thread, kwargs={'list_name': list_name, 'qt_signal': qt_signal})
        request_thread.start()
    
    @staticmethod
    def request_list_options_thread(list_name: str, qt_signal: SignalInstance):
        asyncio.run(DbusWrapper.request_list_options_async(list_name, qt_signal))
    
    @staticmethod
    async def request_list_options_async(list_name: str, qt_signal: SignalInstance):
        dbus_bus = await MessageBus().connect()
        reply = await dbus_bus.call(Message(
            destination=DBUS_BUS_NAME,
            path=DBUS_SETTINGS_OBJECT_PATH,
            interface=DBUS_SETTINGS_INTERFACE_NAME,
            member='GetListOptions',
            message_type=MessageType.METHOD_CALL,
            signature='s',
            body=[list_name],
        ))

        if reply is None:
            DbusWrapper.logger.error('Error getting settings: no reply')

        elif reply.message_type == MessageType.ERROR:
            DbusWrapper.logger.error('Error getting settings: %s', reply.body)

        else:
            obj = {'name': list_name, 'list': json.loads(reply.body[0]) or []}
            qt_signal.emit(obj)

    @staticmethod
    def change_setting(name: str, value: int|bool|str) -> None:
        request_thread = Thread(target=DbusWrapper.change_setting_thread, kwargs={'name': name, 'value': value})
        request_thread.start()
    
    @staticmethod
    def change_setting_thread(name: str, value: int|bool|str):
        asyncio.run(DbusWrapper.change_setting_async(name, value))
    
    @staticmethod
    async def change_setting_async(name: str, value: int|bool|str):
        dbus_bus = await MessageBus().connect()
        await dbus_bus.call(Message(
            destination=DBUS_BUS_NAME,
            path=DBUS_SETTINGS_OBJECT_PATH,
            interface=DBUS_SETTINGS_INTERFACE_NAME,
            member='SetSetting',
            message_type=MessageType.METHOD_CALL,
            signature='ss',
            body=[name, json.dumps(value)],
        ))

    def save_profile(self, name: str) -> None:
        self._run_in_thread('SaveProfile', lambda: self._save_profile_async(name))

    async def _save_profile_async(self, name: str):
        async with self._settings_iface() as iface:
            await iface.call_save_profile(name) # type: ignore
        self.request_settings()

    def load_profile(self, name: str) -> None:
        self._run_in_thread('LoadProfile', lambda: self._load_profile_async(name))

    async def _load_profile_async(self, name: str):
        async with self._settings_iface() as iface:
            await iface.call_load_profile(name) # type: ignore
        self.request_settings()

    def move_application_route(self, stream_index: int, endpoint_node_name: str) -> None:
        self._run_in_thread(
            'MoveApplicationRoute',
            lambda: self._move_application_route_async(stream_index, endpoint_node_name),
        )

    async def _move_application_route_async(self, stream_index: int, endpoint_node_name: str):
        moved = False
        try:
            async with self._settings_iface() as iface:
                moved = bool(await iface.call_move_application_route(stream_index, endpoint_node_name)) # type: ignore
        except Exception:
            self.logger.exception('MoveApplicationRoute failed for stream %s -> %s', stream_index, endpoint_node_name)
        finally:
            self.sig_route_moved.emit(moved, stream_index, endpoint_node_name)
        self.request_settings()
