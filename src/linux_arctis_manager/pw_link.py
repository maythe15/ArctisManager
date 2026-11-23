import logging
import shutil
import subprocess

PW_LINK_TIMEOUT_SECONDS = 5


class PipeWireLinker:
    """Thin wrapper around the `pw-link` CLI.

    The PulseAudio protocol cannot create links between nodes, so this is the
    one place the daemon talks to PipeWire natively. Kept behind a small class
    so tests can replace it.
    """

    def __init__(self, executable: str = 'pw-link'):
        self.executable: str = executable
        self.logger: logging.Logger = logging.getLogger('PipeWireLinker')

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def _run(self, *args: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                [self.executable, *args],
                capture_output=True,
                text=True,
                timeout=PW_LINK_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as e:
            self.logger.warning('Failed to run %s: %s', self.executable, e)
            return None

    def _ports(self, flag: str, node_name: str) -> list[str]:
        result = self._run(flag)
        if result is None or result.returncode != 0:
            return []

        ports = []
        for line in result.stdout.splitlines():
            line = line.strip()
            node, sep, port = line.rpartition(':')
            if sep and node == node_name:
                ports.append(port)

        return ports

    def output_ports(self, node_name: str) -> list[str]:
        return self._ports('--output', node_name)

    def input_ports(self, node_name: str) -> list[str]:
        return self._ports('--input', node_name)

    def link(self, output_port: str, input_port: str) -> bool:
        result = self._run(output_port, input_port)
        if result is None:
            return False
        if result.returncode == 0:
            return True
        # pw-link reports an already existing link as an error; that is fine.
        if 'exists' in (result.stderr or '').lower():
            return True

        self.logger.warning('pw-link %s %s failed: %s', output_port, input_port, (result.stderr or '').strip())
        return False


def port_channel(port_name: str) -> str:
    """`monitor_FL` -> `FL`, `playback_FR` -> `FR`."""
    return port_name.rsplit('_', 1)[-1]
