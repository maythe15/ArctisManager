from dataclasses import dataclass
from typing import Any, Literal, Mapping

from linux_arctis_manager.constants import (
    PULSE_AUX_NODE_NAME,
    PULSE_CHAT_NODE_NAME,
    PULSE_GAME_NODE_NAME,
    PULSE_MEDIA_NODE_NAME,
    PULSE_MICROPHONE_NODE_NAME,
)

EndpointKind = Literal['sink', 'source']
MixGroup = Literal['media', 'chat', 'microphone']

# The two sides of the hardware ChatMix dial an output channel can follow.
ASSIGNABLE_MIX_GROUPS: tuple[MixGroup, ...] = ('media', 'chat')


@dataclass(frozen=True)
class VirtualAudioEndpoint:
    node_name: str
    key: str
    label: str
    kind: EndpointKind
    mix_group: MixGroup
    implemented: bool = True


VIRTUAL_AUDIO_ENDPOINTS: tuple[VirtualAudioEndpoint, ...] = (
    VirtualAudioEndpoint(PULSE_GAME_NODE_NAME, 'game', 'Game', 'sink', 'media'),
    VirtualAudioEndpoint(PULSE_CHAT_NODE_NAME, 'chat', 'Chat', 'sink', 'chat'),
    VirtualAudioEndpoint(PULSE_MEDIA_NODE_NAME, 'media', 'Media', 'sink', 'media'),
    VirtualAudioEndpoint(PULSE_AUX_NODE_NAME, 'aux', 'Aux', 'sink', 'media'),
    VirtualAudioEndpoint(PULSE_MICROPHONE_NODE_NAME, 'microphone', 'Microphone', 'source', 'microphone', implemented=False),
)

VIRTUAL_SINK_ENDPOINTS = tuple(
    endpoint
    for endpoint in VIRTUAL_AUDIO_ENDPOINTS
    if endpoint.kind == 'sink' and endpoint.implemented
)

VIRTUAL_SINK_NODE_NAMES = tuple(endpoint.node_name for endpoint in VIRTUAL_SINK_ENDPOINTS)


# Default ChatMix side for each output channel, keyed by endpoint key.
DEFAULT_MIX_GROUPS: dict[str, MixGroup] = {
    endpoint.key: endpoint.mix_group
    for endpoint in VIRTUAL_SINK_ENDPOINTS
}


def normalize_mix_groups(raw: Any) -> dict[str, MixGroup]:
    """Merge user mix group overrides onto the defaults, ignoring invalid entries."""
    result = dict(DEFAULT_MIX_GROUPS)
    if not isinstance(raw, Mapping):
        return result

    for key, group in raw.items():
        if key in result and group in ASSIGNABLE_MIX_GROUPS:
            result[key] = group

    return result


def endpoint_mix_group(endpoint: VirtualAudioEndpoint, mix_groups: Mapping[str, Any] | None = None) -> MixGroup:
    """Return the mix group an endpoint currently follows, honoring user overrides."""
    if mix_groups is None:
        return endpoint.mix_group

    return normalize_mix_groups(mix_groups).get(endpoint.key, endpoint.mix_group)


def endpoints_for_mix_group(mix_group: MixGroup, mix_groups: Mapping[str, Any] | None = None) -> tuple[VirtualAudioEndpoint, ...]:
    resolved = normalize_mix_groups(mix_groups)
    return tuple(
        endpoint
        for endpoint in VIRTUAL_SINK_ENDPOINTS
        if resolved.get(endpoint.key, endpoint.mix_group) == mix_group
    )
