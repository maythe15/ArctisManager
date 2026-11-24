import asyncio
import json
import logging
from threading import Lock, Thread
from typing import Any, Callable, ClassVar, Coroutine

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

    # All D-Bus traffic goes through one asyncio loop running in a background
    # thread and one MessageBus bound to it. A dbus-next bus only works on the
    # loop that created it, and dbus-next 0.2.3 never closes a bus socket (not
    # even on disconnect()), so opening a connection per request leaked a file
    # descriptor each time and quickly hit "too many open files" when dragging
    # sliders. The loop and bus are shared by every wrapper in the process (the
    # tray and the main window each have one). Requests run in submission order.
    _loop: ClassVar[asyncio.AbstractEventLoop|None] = None
    _loop_guard: ClassVar[Lock] = Lock()
    _bus: ClassVar[MessageBus|None] = None
    _bus_lock: ClassVar[asyncio.Lock|None] = None
    _interfaces: ClassVar[dict[tuple[str, str], ProxyInterface]] = {}

    def __init__(self, parent: QObject|None = None):
        super().__init__(parent)

        self._stopping = False
        self._status_callback: Callable[[str], None]|None = None
        self._settings_callback: Callable[[str], None]|None = None

    @classmethod
    def _get_loop(cls) -> asyncio.AbstractEventLoop:
        with cls._loop_guard:
            if cls._loop is None or cls._loop.is_closed():
                loop = asyncio.new_event_loop()
                Thread(target=loop.run_forever, name='dbus-wrapper-loop', daemon=True).start()
                cls._loop = loop
                cls._bus = None
                cls._bus_lock = None
                cls._interfaces = {}

            return cls._loop

    @staticmethod
    async def _close_bus(bus: MessageBus) -> None:
        try:
            bus.disconnect()
            await asyncio.wait_for(bus.wait_for_disconnect(), timeout=2)
        except Exception:
            pass
        # disconnect() only shuts the socket down; release the descriptor too.
        sock = getattr(bus, '_sock', None)
        if sock is not None:
            sock.close()

    @classmethod
    async def _get_bus(cls) -> MessageBus:
        if cls._bus_lock is None:
            cls._bus_lock = asyncio.Lock()

        async with cls._bus_lock:
            if cls._bus is None or not cls._bus.connected:
                if cls._bus is not None:
                    await cls._close_bus(cls._bus)
                cls._bus = None
                cls._interfaces = {}
                cls._bus = await MessageBus().connect()

            return cls._bus

    @classmethod
    async def _interface(cls, object_path: str, interface_name: str) -> ProxyInterface:
        bus = await cls._get_bus()
        key = (object_path, interface_name)
        if (iface := cls._interfaces.get(key)) is None:
            introspection = await bus.introspect(DBUS_BUS_NAME, object_path)
            obj = bus.get_proxy_object(DBUS_BUS_NAME, object_path, introspection)
            iface = obj.get_interface(interface_name)
            cls._interfaces[key] = iface

        return iface

    @classmethod
    async def _status_iface(cls) -> ProxyInterface:
        return await cls._interface(DBUS_STATUS_OBJECT_PATH, DBUS_STATUS_INTERFACE_NAME)

    @classmethod
    async def _settings_iface(cls) -> ProxyInterface:
        return await cls._interface(DBUS_SETTINGS_OBJECT_PATH, DBUS_SETTINGS_INTERFACE_NAME)

    @classmethod
    def _run_in_thread(cls, description: str, coro_factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
        '''Schedule a request on the shared D-Bus loop thread.'''
        async def runner() -> None:
            try:
                await coro_factory()
            except Exception:
                cls.logger.exception('D-Bus request failed: %s', description)

        asyncio.run_coroutine_threadsafe(runner(), cls._get_loop())

    def start(self):
        self.request_status()
        self.request_settings()

        self._run_in_thread('status signal', self._register_status_dbus_signal)
        self._run_in_thread('settings signal', self._register_settings_dbus_signal)

    async def _register_status_dbus_signal(self):
        def callback(status: str) -> None:
            self.sig_status.emit(json.loads(status) or {})

        iface = await self._status_iface()
        iface.on_status_changed(callback) # type: ignore
        self._status_callback = callback

    async def _register_settings_dbus_signal(self):
        def callback(settings: str) -> None:
            self.sig_settings.emit(json.loads(settings) or {})

        iface = await self._settings_iface()
        iface.on_settings_changed(callback) # type: ignore
        self._settings_callback = callback

    def stop(self):
        self.logger.info("Stopping D-Bus wrapper...")
        self._stopping = True
        self._run_in_thread('unsubscribe signals', self._unregister_dbus_signals)

    async def _unregister_dbus_signals(self):
        if self._status_callback is not None:
            (await self._status_iface()).off_status_changed(self._status_callback) # type: ignore
            self._status_callback = None
        if self._settings_callback is not None:
            (await self._settings_iface()).off_settings_changed(self._settings_callback) # type: ignore
            self._settings_callback = None

    def request_status(self) -> None:
        self._run_in_thread('GetStatus', self._request_status_async)

    async def _request_status_async(self):
        result = await (await self._status_iface()).call_get_status() # type: ignore
        self.sig_status.emit(json.loads(result) or {})

    def request_settings(self) -> None:
        self._run_in_thread('GetSettings', self._request_settings_async)

    async def _request_settings_async(self):
        result = await (await self._settings_iface()).call_get_settings() # type: ignore
        self.sig_settings.emit(json.loads(result) or {})

    @classmethod
    def request_list_options(cls, list_name: str, qt_signal: SignalInstance):
        cls._run_in_thread('GetListOptions', lambda: cls.request_list_options_async(list_name, qt_signal))

    @classmethod
    async def request_list_options_async(cls, list_name: str, qt_signal: SignalInstance):
        bus = await cls._get_bus()
        reply = await bus.call(Message(
            destination=DBUS_BUS_NAME,
            path=DBUS_SETTINGS_OBJECT_PATH,
            interface=DBUS_SETTINGS_INTERFACE_NAME,
            member='GetListOptions',
            message_type=MessageType.METHOD_CALL,
            signature='s',
            body=[list_name],
        ))

        if reply is None:
            cls.logger.error('Error getting settings: no reply')

        elif reply.message_type == MessageType.ERROR:
            cls.logger.error('Error getting settings: %s', reply.body)

        else:
            obj = {'name': list_name, 'list': json.loads(reply.body[0]) or []}
            qt_signal.emit(obj)

    @classmethod
    def change_setting(cls, name: str, value: int|bool|str) -> None:
        cls._run_in_thread(f'SetSetting {name}', lambda: cls.change_setting_async(name, value))

    @classmethod
    async def change_setting_async(cls, name: str, value: int|bool|str):
        bus = await cls._get_bus()
        reply = await bus.call(Message(
            destination=DBUS_BUS_NAME,
            path=DBUS_SETTINGS_OBJECT_PATH,
            interface=DBUS_SETTINGS_INTERFACE_NAME,
            member='SetSetting',
            message_type=MessageType.METHOD_CALL,
            signature='ss',
            body=[name, json.dumps(value)],
        ))
        if reply is not None and reply.message_type == MessageType.ERROR:
            cls.logger.error('Error setting %s: %s', name, reply.body)

    def save_profile(self, name: str) -> None:
        self._run_in_thread('SaveProfile', lambda: self._save_profile_async(name))

    async def _save_profile_async(self, name: str):
        await (await self._settings_iface()).call_save_profile(name) # type: ignore
        self.request_settings()

    def load_profile(self, name: str) -> None:
        self._run_in_thread('LoadProfile', lambda: self._load_profile_async(name))

    async def _load_profile_async(self, name: str):
        await (await self._settings_iface()).call_load_profile(name) # type: ignore
        self.request_settings()

    def move_application_route(self, stream_index: int, endpoint_node_name: str) -> None:
        self._run_in_thread(
            'MoveApplicationRoute',
            lambda: self._move_application_route_async(stream_index, endpoint_node_name),
        )

    async def _move_application_route_async(self, stream_index: int, endpoint_node_name: str):
        moved = False
        try:
            iface = await self._settings_iface()
            moved = bool(await iface.call_move_application_route(stream_index, endpoint_node_name)) # type: ignore
        except Exception:
            self.logger.exception('MoveApplicationRoute failed for stream %s -> %s', stream_index, endpoint_node_name)
        finally:
            self.sig_route_moved.emit(moved, stream_index, endpoint_node_name)
        self.request_settings()

    def set_mix_group(self, channel: str, group: str) -> None:
        self._run_in_thread('SetMixGroup', lambda: self._set_mix_group_async(channel, group))

    async def _set_mix_group_async(self, channel: str, group: str):
        await (await self._settings_iface()).call_set_mix_group(channel, group) # type: ignore
        self.request_settings()
