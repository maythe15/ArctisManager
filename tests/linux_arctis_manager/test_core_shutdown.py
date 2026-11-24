import logging
from pathlib import Path

import usb.core
from ruamel.yaml import YAML

from linux_arctis_manager.config import DeviceConfiguration
from linux_arctis_manager.core import CoreEngine

DEVICES = Path(__file__).parents[2] / 'src' / 'linux_arctis_manager' / 'devices'


def _config(name: str) -> DeviceConfiguration:
    return DeviceConfiguration(YAML(typ='safe').load(DEVICES / name))


class FakeMonitor:
    stopped = False

    def stop(self):
        self.stopped = True


def _shutdown_config() -> DeviceConfiguration:
    raw = YAML(typ='safe').load(DEVICES / 'nova_pro_wireless.yaml')
    raw['device']['device_shutdown'] = [[0x06, 0x8d, 0x00]]
    return DeviceConfiguration(raw)


def _core(device_config: DeviceConfiguration | None, fail: bool = False) -> tuple[CoreEngine, list[list[int]]]:
    sent: list[list[int]] = []
    core = object.__new__(CoreEngine)
    core.logger = logging.getLogger('test')
    core.usb_devices_monitor = FakeMonitor()  # pyright: ignore[reportAttributeAccessIssue]
    core.usb_device = object()  # pyright: ignore[reportAttributeAccessIssue]
    core.device_config = device_config
    core.get_command_endpoint_address = lambda: 0x04  # pyright: ignore[reportAttributeAccessIssue]

    def send_command(command, endpoint, interface=0):
        if fail:
            raise usb.core.USBError('gone')
        sent.append(command)

    core.send_command = send_command  # pyright: ignore[reportAttributeAccessIssue]
    return core, sent


def test_config_without_device_shutdown_defaults_to_none():
    assert _config('arctis_7_plus.yaml').device_shutdown is None
    assert _config('nova_pro_wireless.yaml').device_shutdown is None


def test_stop_sends_device_shutdown_sequence():
    core, sent = _core(_shutdown_config())

    core.stop()

    assert sent == [[0x06, 0x8d, 0x00]]
    assert core.usb_devices_monitor.stopped  # pyright: ignore[reportAttributeAccessIssue]


def test_stop_without_device_sends_nothing():
    core, sent = _core(None)
    core.usb_device = None

    core.stop()

    assert sent == []


def test_stop_survives_usb_errors_during_shutdown_sequence():
    core, _ = _core(_shutdown_config(), fail=True)

    core.stop()

    assert core.usb_devices_monitor.stopped  # pyright: ignore[reportAttributeAccessIssue]
