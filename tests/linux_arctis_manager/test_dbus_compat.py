import asyncio
from queue import Queue

from dbus_next.aio import message_bus as aio_message_bus

from linux_arctis_manager.dbus_compat import patch_dbus_next


class FullThenFreeSocket:
    '''send() reports a full buffer (EAGAIN) a few times, then accepts everything.'''

    def __init__(self, full_times: int):
        self.full_times = full_times
        self.sent = b''

    def send(self, data):
        if self.full_times:
            self.full_times -= 1
            raise BlockingIOError(11, 'Resource temporarily unavailable')
        self.sent += bytes(data)
        return len(data)


class FakeLoop:
    def __init__(self):
        self.writer_removed = False

    def remove_writer(self, _fd):
        self.writer_removed = True


class FakeBus:
    def __init__(self):
        self.finalized_with = None

    def _finalize(self, err):
        self.finalized_with = err


def _writer(sock) -> tuple[aio_message_bus._MessageWriter, FakeBus, FakeLoop]:
    writer = object.__new__(aio_message_bus._MessageWriter)
    bus, loop = FakeBus(), FakeLoop()
    writer.messages = Queue()
    writer.negotiate_unix_fd = False
    writer.bus = bus
    writer.sock = sock
    writer.loop = loop
    writer.buf = None
    writer.fd = 0
    writer.offset = 0
    writer.unix_fds = None
    writer.fut = None
    return writer, bus, loop


def test_full_send_buffer_waits_instead_of_killing_the_bus():
    patch_dbus_next()
    sock = FullThenFreeSocket(full_times=2)
    writer, bus, loop = _writer(sock)
    future = asyncio.new_event_loop().create_future()
    writer.messages.put_nowait((b'hello', [], future))

    # Socket not writable: the writer must keep the message and stay registered.
    writer.write_callback()
    writer.write_callback()
    assert bus.finalized_with is None
    assert not loop.writer_removed
    assert not future.done()

    # Socket writable again ("writable" event): message goes out, writer unregisters.
    writer.write_callback()
    assert sock.sent == b'hello'
    assert future.done() and future.exception() is None
    assert loop.writer_removed
    assert bus.finalized_with is None


def test_real_socket_errors_still_finalize_the_bus():
    patch_dbus_next()

    class BrokenSocket:
        def send(self, _data):
            raise BrokenPipeError(32, 'Broken pipe')

    writer, bus, _ = _writer(BrokenSocket())
    writer.messages.put_nowait((b'hello', [], None))

    writer.write_callback()

    assert isinstance(bus.finalized_with, BrokenPipeError)


def test_patch_is_idempotent():
    patch_dbus_next()
    first = aio_message_bus._MessageWriter.write_callback
    patch_dbus_next()
    assert aio_message_bus._MessageWriter.write_callback is first


def test_settings_changed_burst_is_coalesced_into_one_signal():
    from linux_arctis_manager.dbus_service import ArctisManagerDbusSettingsService

    service = object.__new__(ArctisManagerDbusSettingsService)
    emitted: list[int] = []
    service._emit_settings_changed = lambda: (setattr(service, '_settings_signal_pending', False), emitted.append(1))  # type: ignore[method-assign]

    async def drag_slider():
        for _ in range(50):  # one SetSetting per slider tick
            service.notify_settings_changed()
        await asyncio.sleep(service.SETTINGS_SIGNAL_DELAY * 2)
        service.notify_settings_changed()  # a later change still gets its own signal
        await asyncio.sleep(service.SETTINGS_SIGNAL_DELAY * 2)

    asyncio.run(drag_slider())

    assert emitted == [1, 1]
