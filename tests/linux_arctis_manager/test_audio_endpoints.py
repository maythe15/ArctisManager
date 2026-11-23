from linux_arctis_manager.audio_endpoints import (
    DEFAULT_MIX_GROUPS,
    VIRTUAL_AUDIO_ENDPOINTS,
    VIRTUAL_SINK_ENDPOINTS,
    VIRTUAL_SINK_NODE_NAMES,
    endpoint_mix_group,
    endpoints_for_mix_group,
    normalize_mix_groups,
)
from linux_arctis_manager.constants import (
    PULSE_AUX_NODE_NAME,
    PULSE_CHAT_NODE_NAME,
    PULSE_GAME_NODE_NAME,
    PULSE_MEDIA_NODE_NAME,
    PULSE_MICROPHONE_NODE_NAME,
)


def test_sonar_style_endpoint_catalog_includes_expected_channels():
    assert [endpoint.node_name for endpoint in VIRTUAL_AUDIO_ENDPOINTS] == [
        PULSE_GAME_NODE_NAME,
        PULSE_CHAT_NODE_NAME,
        PULSE_MEDIA_NODE_NAME,
        PULSE_AUX_NODE_NAME,
        PULSE_MICROPHONE_NODE_NAME,
    ]


def test_virtual_sink_endpoints_are_the_implemented_outputs():
    assert VIRTUAL_SINK_NODE_NAMES == (
        PULSE_GAME_NODE_NAME,
        PULSE_CHAT_NODE_NAME,
        PULSE_MEDIA_NODE_NAME,
        PULSE_AUX_NODE_NAME,
    )
    assert all(endpoint.kind == 'sink' for endpoint in VIRTUAL_SINK_ENDPOINTS)


def test_media_mix_group_covers_non_chat_outputs():
    assert [endpoint.node_name for endpoint in endpoints_for_mix_group('media')] == [
        PULSE_GAME_NODE_NAME,
        PULSE_MEDIA_NODE_NAME,
        PULSE_AUX_NODE_NAME,
    ]


def test_chat_mix_group_only_covers_chat_output():
    assert [endpoint.node_name for endpoint in endpoints_for_mix_group('chat')] == [
        PULSE_CHAT_NODE_NAME,
    ]


def test_default_mix_groups_cover_every_output_channel():
    assert DEFAULT_MIX_GROUPS == {
        'game': 'media',
        'chat': 'chat',
        'media': 'media',
        'aux': 'media',
    }


def test_normalize_mix_groups_merges_valid_overrides_onto_defaults():
    assert normalize_mix_groups({
        'aux': 'chat',
        'chat': 'media',
        'microphone': 'chat',
        'game': 'microphone',
        'unknown': 'chat',
    }) == {
        'game': 'media',
        'chat': 'media',
        'media': 'media',
        'aux': 'chat',
    }
    assert normalize_mix_groups(None) == DEFAULT_MIX_GROUPS
    assert normalize_mix_groups(['aux']) == DEFAULT_MIX_GROUPS


def test_mix_group_overrides_change_endpoint_membership():
    overrides = {'aux': 'chat', 'media': 'chat'}

    assert [endpoint.node_name for endpoint in endpoints_for_mix_group('media', overrides)] == [
        PULSE_GAME_NODE_NAME,
    ]
    assert [endpoint.node_name for endpoint in endpoints_for_mix_group('chat', overrides)] == [
        PULSE_CHAT_NODE_NAME,
        PULSE_MEDIA_NODE_NAME,
        PULSE_AUX_NODE_NAME,
    ]
    aux = next(endpoint for endpoint in VIRTUAL_AUDIO_ENDPOINTS if endpoint.key == 'aux')
    assert endpoint_mix_group(aux, overrides) == 'chat'
    assert endpoint_mix_group(aux) == 'media'
