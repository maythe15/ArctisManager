import logging
import time
from typing import Any, Mapping

import pulsectl

from linux_arctis_manager.audio_endpoints import (VIRTUAL_AUDIO_ENDPOINTS,
                                                  VIRTUAL_SINK_ENDPOINTS,
                                                  VIRTUAL_SINK_NODE_NAMES,
                                                  endpoint_mix_group,
                                                  endpoints_for_mix_group)
from linux_arctis_manager.constants import STEELSERIES_VENDOR_ID
from linux_arctis_manager.pw_link import PipeWireLinker, port_channel

ONLY_PHYSICAL = 1
ONLY_VIRTUAL = 2
ALL_SINKS = 3

# Marks a null sink created by the direct-link layout (see create_virtual_sink).
DIRECT_SINK_MARKER = 'monitor.channel-volumes=true'
LINK_PORT_ATTEMPTS = 20
LINK_PORT_RETRY_SECONDS = 0.1

class TypedPulseSinkInfo(pulsectl.PulseSinkInfo):
    name: str


class TypedPulseSinkInputInfo(pulsectl.PulseSinkInputInfo):
    index: int
    name: str
    sink: int


class PulseAudioManager:
    _instance: 'PulseAudioManager|None' = None

    @staticmethod
    def get_instance() -> 'PulseAudioManager':
        if PulseAudioManager._instance is None:
            PulseAudioManager._instance = PulseAudioManager()

        return PulseAudioManager._instance

    def __init__(self):
        self.pulse = pulsectl.Pulse('linux-arctis-manager')
        self.logger = logging.getLogger('PulseAudioManager')
        self.linker = PipeWireLinker()

    def sink_list_wrapper(self) -> list[TypedPulseSinkInfo]:
        retry_attempts = 15

        sinks: list[TypedPulseSinkInfo] = []
        while retry_attempts > 0:
            try:
                sinks = self.pulse.sink_list()
                break
            except pulsectl.PulseError as e:
                self.logger.error(f'Error while getting sink list: {e}')
                retry_attempts -= 1
                time.sleep(1)

        sinks: list[TypedPulseSinkInfo] = sinks if type(sinks) is list else [sinks] # pyright: ignore[reportAssignmentType]

        return sinks
    
    def get_arctis_sinks(self, mode: int = ALL_SINKS, vendor_id: int = STEELSERIES_VENDOR_ID, product_id: int|list[int]|None = None) -> list[TypedPulseSinkInfo]:
        sinks = self.sink_list_wrapper()

        def check_prod_id(product_id_attr: str) -> bool:
            if product_id is None:
                return True

            lst = product_id if type(product_id) is list else [product_id]

            return product_id_attr in [f'0x{pid:04x}' for pid in lst]

        physical = [s for s in sinks if s.proplist.get('device.vendor.id', '') == f'0x{vendor_id:04x}' and check_prod_id(s.proplist.get('device.product.id', ''))]
        virtual = [s for s in sinks if s.proplist.get('node.name', '') in VIRTUAL_SINK_NODE_NAMES]

        if mode == ONLY_PHYSICAL:
            sinks = physical
        elif mode == ONLY_VIRTUAL:
            sinks = virtual
        else:
            sinks = physical + virtual

        return sinks

    def create_virtual_sink(self, name: str, description: str, sink_output: str) -> None:
        direct = self.linker.available()
        module = self._virtual_sink_module(name)
        if module is not None:
            layout = self._virtual_sink_layout(module)
            if direct and layout == 'direct':
                # Links vanish whenever the headset node goes away, so check them again.
                if self._link_virtual_sink(name, sink_output):
                    return
                self.logger.warning(f'Could not re-link virtual sink "{name}", rebuilding it')
            elif not direct and layout == 'remap':
                return
            # Anything else (old null sink + loopback, a remap sink when pw-link is
            # now available, a direct sink without pw-link) is rebuilt.
            self.remove_virtual_sink(name)

        if direct:
            self.logger.info(f'Creating virtual sink "{name}" linked to "{sink_output}"...')
            if self._create_direct_virtual_sink(name, description, sink_output):
                return
            self.logger.warning(f'Falling back to module-remap-sink for "{name}"')
            self.remove_virtual_sink(name)
        else:
            self.logger.info(f'pw-link not found, creating remap sink "{name}" -> "{sink_output}"...')

        self._create_remap_virtual_sink(name, description, sink_output)

    @staticmethod
    def _sink_description(description: str) -> str:
        # The description is nested inside two levels of module-argument quoting.
        return ''.join(c for c in description if c not in '\\\'"')

    def _create_direct_virtual_sink(self, name: str, description: str, sink_output: str) -> bool:
        # A single null-sink node whose monitor ports are linked straight to the
        # headset. monitor.channel-volumes makes the sink volume and mute (and so
        # ChatMix) apply to the monitor ports; PipeWire ignores them otherwise.
        self.pulse.module_load(
            'module-null-sink',
            f'sink_name={name} '
            f"sink_properties='node.description=\"{self._sink_description(description)}\" "
            f"{DIRECT_SINK_MARKER}'"
        )

        return self._link_virtual_sink(name, sink_output)

    def _create_remap_virtual_sink(self, name: str, description: str, sink_output: str) -> None:
        # Fallback without pw-link: one sink node plus an internal playback stream.
        # Works on plain PulseAudio too, but on PipeWire the two nodes are not
        # joined by a visible link.
        escaped_node_description = description.replace(' ', '\\ ')
        self.pulse.module_load(
            'module-remap-sink',
            f'sink_name={name} '
            f'sink_properties=node.description="{escaped_node_description}" '
            f'master={sink_output}'
        )

    def _link_virtual_sink(self, name: str, sink_output: str) -> bool:
        """Link `<name>:monitor_*` to `<sink_output>:playback_*`, channel by channel."""
        attempts = LINK_PORT_ATTEMPTS
        while True:
            outputs = [p for p in self.linker.output_ports(name) if p.startswith('monitor_')]
            inputs = [p for p in self.linker.input_ports(sink_output) if p.startswith('playback_')]
            if outputs and inputs:
                break
            attempts -= 1
            if attempts <= 0:
                self.logger.warning(f'Ports for "{name}" -> "{sink_output}" did not appear')
                return False
            # Ports show up shortly after the module loads.
            time.sleep(LINK_PORT_RETRY_SECONDS)

        inputs_by_channel = {port_channel(p): p for p in inputs}
        pairs: list[tuple[str, str]] = []
        for output in outputs:
            target = inputs_by_channel.get(port_channel(output))
            if target is None and len(inputs) == 1:
                # Mono headset sink: fold every channel into it.
                target = inputs[0]
            if target is not None:
                pairs.append((output, target))

        if not pairs:
            self.logger.warning(f'No matching channels between "{name}" and "{sink_output}"')
            return False

        return all([
            self.linker.link(f'{name}:{output}', f'{sink_output}:{target}')
            for output, target in pairs
        ])

    def _virtual_sink_module(self, name: str) -> Any | None:
        return next((
            module
            for module in self.pulse.module_list()
            if module.name in ('module-null-sink', 'module-remap-sink')
            and f'sink_name={name}' in (module.argument or '').split()
        ), None)

    @staticmethod
    def _virtual_sink_layout(module: Any) -> str:
        if module.name == 'module-remap-sink':
            return 'remap'
        if DIRECT_SINK_MARKER in (module.argument or ''):
            return 'direct'
        return 'legacy'
    
    def remove_virtual_sink(self, name: str) -> None:
        sink = next((s for s in self.get_arctis_sinks(ONLY_VIRTUAL) if s.proplist.get('node.name', '') == name), None)
        if not sink:
            return
        
        self.logger.info(f'Removing virtual sink "{name}"...')
        modules = self.pulse.module_list()
        for module in modules:
            if module.argument and name in module.argument:
                self.pulse.module_unload(module.index)
    
    def wait_for_physical_device(self, vendor_id: int, product_id: int, attempts: int = 10) -> bool:
        vendor_id_hex = f'0x{vendor_id:04x}'
        product_id_hex = f'0x{product_id:04x}'

        while attempts > 0:
            if next((s for s in self.get_arctis_sinks(ONLY_PHYSICAL, vendor_id=vendor_id, product_id=product_id)), None):
                return True

            attempts -= 1
            time.sleep(1)
        
        self.logger.error(f'Failed to find SteelSeries Arctis device {vendor_id:04x}:{product_id:04x} after {attempts} attempts')

        return False

    def redirect_audio(self, output_sink_node_name: str) -> None:
        self.logger.info(f'Redirecting audio to {output_sink_node_name}...')

        sink = next((s for s in self.sink_list_wrapper() if s.proplist.get('node.nick', '') == output_sink_node_name or s.proplist.get('node.name', '') == output_sink_node_name), None)
        if sink is None:
            self.logger.error(f'Failed to find sink {output_sink_node_name} to set it as default')
            return
        self.pulse.default_set(sink)
    
    def get_default_device(self) -> TypedPulseSinkInfo|None:
        server_info = self.pulse.server_info()
        default_sink_name: str|None = getattr(server_info, 'default_sink_name', None)

        if default_sink_name is None:
            return None
        
        sink = next((s for s in self.sink_list_wrapper() if s.proplist.get('node.name', '') == default_sink_name), None)

        return sink

    def virtual_endpoint_statuses(self, mix_groups: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        try:
            sinks = self.pulse.sink_list()
        except pulsectl.PulseError as e:
            self.logger.warning('Failed to read virtual audio endpoints: %s', e)
            sinks = []

        if sinks is None:
            sinks = []
        sinks = sinks if type(sinks) is list else [sinks] # pyright: ignore[reportAssignmentType]
        sinks = [s for s in sinks if s.proplist.get('node.name', '') in VIRTUAL_SINK_NODE_NAMES]
        sinks_by_node_name = {s.proplist.get('node.name', ''): s for s in sinks}

        default_sink_name = None
        try:
            default_sink_name = getattr(self.pulse.server_info(), 'default_sink_name', None)
        except pulsectl.PulseError as e:
            self.logger.warning('Failed to read default PulseAudio sink: %s', e)

        result = []
        for endpoint in VIRTUAL_AUDIO_ENDPOINTS:
            sink = sinks_by_node_name.get(endpoint.node_name)
            result.append({
                'node_name': endpoint.node_name,
                'label': endpoint.label,
                'kind': endpoint.kind,
                'mix_group': endpoint_mix_group(endpoint, mix_groups),
                'implemented': endpoint.implemented,
                'present': sink is not None,
                'default': sink is not None and sink.proplist.get('node.name', '') == default_sink_name,
                'description': sink.proplist.get('node.description', '') if sink else '',
            })

        return result

    def application_routes(self) -> list[dict[str, Any]]:
        try:
            sinks = self.pulse.sink_list()
            sink_inputs = self.pulse.sink_input_list()
        except pulsectl.PulseError as e:
            self.logger.warning('Failed to read active application routes: %s', e)
            return []

        if sinks is None:
            sinks = []
        if sink_inputs is None:
            sink_inputs = []

        sinks = sinks if type(sinks) is list else [sinks] # pyright: ignore[reportAssignmentType]
        sink_inputs = sink_inputs if type(sink_inputs) is list else [sink_inputs] # pyright: ignore[reportAssignmentType]

        sinks_by_index = {getattr(sink, 'index', -1): sink for sink in sinks}
        virtual_sinks_by_node_name = {
            sink.proplist.get('node.name', ''): sink
            for sink in sinks
            if sink.proplist.get('node.name', '') in VIRTUAL_SINK_NODE_NAMES
        }

        result = []
        for stream in sink_inputs:
            app_name = stream.proplist.get('application.name') or stream.proplist.get('application.process.binary')
            if not app_name:
                continue

            sink = sinks_by_index.get(getattr(stream, 'sink', -1))
            sink_node_name = sink.proplist.get('node.name', '') if sink else ''
            sink_description = sink.proplist.get('node.description', '') if sink else ''
            current_endpoint = next((
                endpoint
                for endpoint in VIRTUAL_SINK_ENDPOINTS
                if endpoint.node_name == sink_node_name
            ), None)

            result.append({
                'stream_index': getattr(stream, 'index', -1),
                'name': getattr(stream, 'name', '') or app_name,
                'application_name': app_name,
                'process_binary': stream.proplist.get('application.process.binary', ''),
                'process_id': stream.proplist.get('application.process.id', ''),
                'sink_index': getattr(stream, 'sink', -1),
                'sink_node_name': sink_node_name,
                'sink_description': sink_description,
                'current_endpoint_node_name': current_endpoint.node_name if current_endpoint else '',
                'current_endpoint_label': current_endpoint.label if current_endpoint else '',
                'routable': bool(virtual_sinks_by_node_name),
            })

        return result

    def move_application_route(self, stream_index: int, endpoint_node_name: str) -> bool:
        if endpoint_node_name not in VIRTUAL_SINK_NODE_NAMES:
            self.logger.warning('Refusing to route stream %s to unsupported endpoint %s', stream_index, endpoint_node_name)
            return False

        try:
            sinks = self.pulse.sink_list()
        except pulsectl.PulseError as e:
            self.logger.warning('Failed to read sinks before moving stream: %s', e)
            return False

        if sinks is None:
            sinks = []
        sinks = sinks if type(sinks) is list else [sinks] # pyright: ignore[reportAssignmentType]

        sink = next((
            sink
            for sink in sinks
            if sink.proplist.get('node.name', '') == endpoint_node_name
        ), None)
        if sink is None:
            self.logger.warning('Refusing to route stream %s because endpoint %s is missing', stream_index, endpoint_node_name)
            return False

        try:
            self.pulse.sink_input_move(stream_index, sink.index)
        except pulsectl.PulseError as e:
            self.logger.warning('Failed to route stream %s to %s: %s', stream_index, endpoint_node_name, e)
            return False

        return True

    def set_mix(self, media_mix: int, chat_mix: int, mix_groups: Mapping[str, str] | None = None):
        if media_mix > 100:
            media_mix = 100
        if chat_mix > 100:
            chat_mix = 100

        sinks = self.get_arctis_sinks(ONLY_VIRTUAL)

        sinks_by_node_name = {s.proplist.get('node.name', ''): s for s in sinks}

        for endpoint in endpoints_for_mix_group('media', mix_groups):
            if sink := sinks_by_node_name.get(endpoint.node_name):
                self.pulse.volume_set_all_chans(sink, media_mix / 100)
        for endpoint in endpoints_for_mix_group('chat', mix_groups):
            if sink := sinks_by_node_name.get(endpoint.node_name):
                self.pulse.volume_set_all_chans(sink, chat_mix / 100)

    def sinks_setup(self, device_name: str, vendor_id: int, product_id: int|list[int]|None):
        real_sink = self.get_arctis_sinks(ONLY_PHYSICAL, vendor_id=vendor_id, product_id=product_id)

        if not real_sink:
            self.logger.warning('No SteelSeries Arctis sink found.')
            return
        
        for endpoint in VIRTUAL_SINK_ENDPOINTS:
            self.create_virtual_sink(endpoint.node_name, f'{device_name} {endpoint.label}', real_sink[0].name)

    def sinks_teardown(self):
        self.logger.info('Removing virtual sinks...')

        for endpoint in VIRTUAL_SINK_ENDPOINTS:
            self.remove_virtual_sink(endpoint.node_name)
