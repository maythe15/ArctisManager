'''
Workarounds for dbus-next 0.2.3 (the last release; the project is unmaintained).

Its asyncio message writer treats a full socket send buffer (EAGAIN /
BlockingIOError) as a fatal error and tears the whole bus down. A burst of
messages (e.g. dragging a slider, which makes the daemon broadcast the settings
for every tick) fills the buffer and kills the connection: the daemon stops
answering and clients see no device. A non-blocking socket that is not writable
yet just needs the writer to wait for the next "writable" event, which is what
this patch does.
'''
import array
import socket

from dbus_next.aio import message_bus as _aio_message_bus

_PATCHED_FLAG = '_lam_eagain_patched'


def _write_callback(self) -> None:
    try:
        while True:
            if self.buf is None:
                if self.messages.qsize() == 0:
                    # nothing more to write
                    self.loop.remove_writer(self.fd)
                    return
                buf, unix_fds, fut = self.messages.get_nowait()
                self.unix_fds = unix_fds
                self.buf = memoryview(buf)
                self.offset = 0
                self.fut = fut

            try:
                if self.unix_fds and self.negotiate_unix_fd:
                    ancdata = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', self.unix_fds))]
                    self.offset += self.sock.sendmsg([self.buf[self.offset:]], ancdata)
                    self.unix_fds = None
                else:
                    self.offset += self.sock.send(self.buf[self.offset:])
            except (BlockingIOError, InterruptedError):
                # Send buffer full: stay registered and resume when writable.
                return

            if self.offset >= len(self.buf):
                # finished writing
                self.buf = None
                _aio_message_bus._future_set_result(self.fut, None)
            else:
                # wait for writable
                return
    except Exception as e:
        _aio_message_bus._future_set_exception(self.fut, e)
        self.bus._finalize(e)


def patch_dbus_next() -> None:
    '''Idempotently install the workarounds above.'''
    writer = _aio_message_bus._MessageWriter
    if getattr(writer, _PATCHED_FLAG, False):
        return

    writer.write_callback = _write_callback
    setattr(writer, _PATCHED_FLAG, True)
