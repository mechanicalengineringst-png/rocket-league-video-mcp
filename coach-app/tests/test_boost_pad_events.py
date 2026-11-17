"""Boost-pad event contract tests: native evidence, never guessed proximity."""
import pytest

from coach_app.boost_pad_events import (
    PADS, make_pad_timeline, match_boost_pickup, pad_state_at,
)


def test_canonical_soccar_pad_coverage():
    assert len(PADS) == 34
    assert [pad['id'] for pad in PADS] == list(range(34))
    assert sum(pad['big'] for pad in PADS) == 6
    assert sum(not pad['big'] for pad in PADS) == 28
    assert {pad['respawnSeconds'] for pad in PADS} == {4, 10}


def test_native_small_pickup_player_offset_matches_correct_pad():
    # Real reported format: boost_pickups payload has pad_type / player_position.
    result = match_boost_pickup({
        'pad_type': 'small',
        'player_position': [0.0, 4402.5, 86.4],
        'boost_before': 70.7, 'boost_after': 98.1,
    })
    assert result['padId'] == 29
    assert result['padType'] == 'small'
    assert result['padMatch'] == 'player_position_nearest'


def test_big_pad_respects_size_and_pickup_radius():
    result = match_boost_pickup({
        'pad_type': 'large',
        'player_position': [-3100.0, -4100.0, 92.0],
    })
    assert result['padId'] == 0
    assert result['padType'] == 'big'
    assert result['padDistance'] < 35


def test_explicit_pad_position_matches_tight_radius():
    result = match_boost_pickup({
        'pad_type': 'small', 'pad_position': [0, -4240, 70],
        'player_position': [500, 500, 17],
    })
    assert result['padId'] == 6
    assert result['padMatch'] == 'pad_position'


@pytest.mark.parametrize('payload', [
    {'pad_type': 'small', 'player_position': [0, 0, 70]},
    {'pad_type': 'small', 'player_position': [float('nan'), 4240, 70]},
    {'pad_type': 'small', 'player_position': [9000, 9000, 70]},
    {'pad_type': 'small', 'player_position': [0]},
    {'pad_type': 'unknown', 'player_position': [0, 4240, 70]},
    {'player_position': [0, 4240, 70]},
])
def test_unknown_or_remote_pad_is_left_unmatched(payload):
    assert match_boost_pickup(payload) is None


def test_timeline_pickups_reset_and_mismatch_statistics():
    native = [{
        'meta': {'stream': 'boost_respawn', 'timing': {'time': 4.0}},
        'payload': {'payload': {
            'kind': 'kickoff', 'time': 4.0,
        }},
    } for _ in range(4)]
    events = [
        {'type': 'boost_pickups', 't': 5.0, 'padId': 0,
         'padMatch': 'player_position_nearest', 'playerId': 'x'},
        {'type': 'boost_pickups', 't': 5.5},  # no trustworthy pad identity
        {'type': 'boost_pickups', 't': 9.0, 'padId': 29,
         'padMatch': 'player_position_nearest', 'playerId': None},
        {'type': 'kickoff', 't': 11.0},
    ]
    timeline = make_pad_timeline(events, native, 4.0, 20.0)
    assert timeline['schema'] == 'replay-lab/boost-pads-v1'
    assert timeline['resets'] == [4.0, 11.0]
    assert timeline['observedPickupCount'] == 3
    assert timeline['unmatchedPickupCount'] == 1
    assert [e['padId'] for e in timeline['pickups']] == [0, 29]
    assert pad_state_at(timeline, 0, 9.0)['remaining'] == 6.0
    assert pad_state_at(timeline, 29, 11.0)['available'] is True
    assert pad_state_at(timeline, 0, 11.0)['available'] is True  # kickoff reset
    assert pad_state_at(timeline, 0, 5.0)['available'] is False


def test_small_pad_respawns_after_four_seconds():
    timeline = make_pad_timeline(
        [{'type': 'boost_pickups', 't': 8.0, 'padId': 6,
          'padMatch': 'player_position_nearest'}], [], 0, 20
    )
    assert pad_state_at(timeline, 6, 11.9)['available'] is False
    assert pad_state_at(timeline, 6, 12)['available'] is True
    # No kickoff/reset or pickup for pad 5: do not invent an available state.
    assert pad_state_at(timeline, 5, 11.9)['available'] is None


def test_no_pickup_stream_marks_coverage_unknown_not_guaranteed_active():
    timeline = make_pad_timeline([], [], 0, 10)
    assert timeline['source'] == 'unavailable'
    assert timeline['observedPickupCount'] == 0
    assert pad_state_at(timeline, 0, 5)['available'] is None
    assert pad_state_at(timeline, 0, 5)['remaining'] is None



def test_unmatched_small_pickup_does_not_fabricate_available_pad_state():
    events = [
        {'type':'boost_pickups','t':7.5,'padType':'small'},
        {'type':'kickoff','t':4},
    ]
    timeline = make_pad_timeline(events, [], 0, 20)
    assert timeline['unmatchedPickupCount'] == 1
    assert timeline['unmatchedPickups'] == [{'t':7.5,'padType':'small'}]
    assert pad_state_at(timeline, 6, 8.0) == {'available':None,'remaining':None}
    assert pad_state_at(timeline, 0, 8.0)['available'] is True
    assert pad_state_at(timeline, 6, 11.5)['available'] is True


def test_a_matching_pickup_proves_cooldown_even_during_unknown_events():
    events = [
        {'type':'kickoff','t':4},
        {'type':'boost_pickups','t':7,'padId':6,
         'padMatch':'player_position_nearest'},
        {'type':'boost_pickups','t':7.2,'padType':'small'},
    ]
    timeline = make_pad_timeline(events, [], 0, 20)
    assert pad_state_at(timeline, 6, 8)['available'] is False
    assert pad_state_at(timeline, 6, 11.01)['available'] is None
    assert pad_state_at(timeline, 6, 11.2)['available'] is True
