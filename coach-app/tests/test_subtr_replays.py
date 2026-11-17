import numpy as np
import pytest

from coach_app.subtr_replays import normalize_subtr_replay, SubtrReplayError


def fixture(swapped=True):
    gh = ['Ball - position x', 'Ball - position y', 'Ball - position z',
          'Ball - linear velocity x', 'Ball - linear velocity y', 'Ball - linear velocity z',
          'current time', 'seconds remaining']
    ph = ['position x', 'position y', 'position z',
          'linear velocity x', 'linear velocity y', 'linear velocity z',
          'rotation x', 'rotation y', 'rotation z',
          'boost level (raw replay units)', 'any_jump_active']
    blue = {'name': 'Blue Player', 'remote_id': {'Xbox': '111'}}
    orange = {'name': 'Orange Player', 'remote_id': {'Epic': '222'}}
    meta = {'column_headers': {'global_headers': gh, 'player_headers': ph},
            'replay_meta': {'team_zero': [blue], 'team_one': [orange], 'all_headers': [['PlayerName','Orange Player']]}}
    # Orange first in ndarray, blue second, deliberately different from metadata order.
    a = [256.,3840.,17.,0.,0.,0.,0.,0.,-1.571,85.,1.]
    b = [-256.,-3840.,17.,0.,0.,0.,0.,0.,1.571,255.,0.]
    blocks = (a+b) if swapped else (b+a)
    matrix = np.array([
        [0,0,93,0,0,0,4.,300.]+blocks,
        [100,-100,93,500,200,0,4.1,300.]+blocks,
        [200,-200,93,500,200,0,4.2,299.]+blocks,
    ], dtype=np.float32)
    events = {'events': [
        {'meta': {'stream':'boost_respawn', 'timing':{'time':4}},
         'payload':{'payload':{'kind':'kickoff','player_id':{'Epic':'222'},'player_position':[256,3840,17],'time':4}}},
        {'meta': {'stream':'boost_respawn', 'timing':{'time':4}},
         'payload':{'payload':{'kind':'kickoff','player_id':{'Xbox':'111'},'player_position':[-256,-3840,17],'time':4}}},
        {'meta': {'stream':'touch','timing':{'frame':100,'time':4.11},'primary_player':{'Epic':'222'}},
         'payload':{'payload':{'frame':100,'time':4.11,'player':{'Epic':'222'},'ball_speed_change':402.25,'tags':[{'group':'kind','value':'control'},{'group':'height_band','value':'ground'}]}}},
        {'meta': {'stream':'goal_context','timing':{'frame':505,'time':4.2}},
         'payload':{'payload':{'frame':505,'time':4.2,'scorer':{'Epic':'222'},'scoring_team_is_team_0':False}}},
    ]}
    return meta, matrix, events


def test_single_file_normalization_preserves_full_rate_and_team_identity():
    meta, arr, events = fixture()
    r = normalize_subtr_replay(meta, arr, events)
    assert r['playerMappingVerified'] is True
    assert [p['name'] for p in r['players']] == ['Orange Player','Blue Player']
    assert r['mode'] == '1v1'
    assert r['primaryPlayerId'] == 'Epic:222'
    assert len(r['frames']) == 3
    assert r['frames'][0]['cars']['Epic:222']['boost'] == pytest.approx(33.3)
    assert r['frames'][0]['cars']['Xbox:111']['boost'] == 100.0
    assert r['frames'][1]['ball']['velocity'] == [500., 200., 0.]
    assert r['frames'][0]['cars']['Epic:222']['jumpActive'] is True
    assert r['frames'][0]['cars']['Xbox:111']['jumpActive'] is False
    assert r['frames'][0]['cars']['Epic:222']['rotation'][2] == pytest.approx(-1.571,abs=0.001)
    assert r['events'][0]['t'] == 4.11
    assert r['events'][0]['nativeFrame'] == 100
    assert r['events'][0]['sampleIndex'] == 1  # NOT frame number 100
    assert r['events'][0]['touchKind'] == 'control'
    assert r['events'][0]['touchHeightBand'] == 'ground'
    assert r['events'][0]['ballSpeedChange'] == pytest.approx(402.2,abs=0.1)
    assert r['events'][1]['scorerId'] == 'Epic:222'
    assert r['events'][1]['sampleIndex'] == 2


def test_missing_precise_replay_clock_fails_instead_of_using_native_frame_index():
    meta, arr, events = fixture()
    meta['column_headers']['global_headers'][6] = 'not a timestamp'
    with pytest.raises(SubtrReplayError, match='current time'):
        normalize_subtr_replay(meta, arr, events)


def test_unverified_mapping_is_labeled():
    meta, arr, events = fixture(swapped=False)
    events['events'] = [ev for ev in events['events'] if ev['meta']['stream'] != 'boost_respawn']
    r = normalize_subtr_replay(meta, arr, events)
    assert r['playerMappingVerified'] is False
    assert any('verify' in note.lower() for note in r['notes'])


def test_rejects_shape_mismatch():
    meta, arr, events = fixture()
    with pytest.raises(SubtrReplayError, match='headers'):
        normalize_subtr_replay(meta, arr[:,:-1], events)


def test_normalized_native_replay_exposes_boost_pad_timeline():
    meta, arr, events = fixture()
    events['events'].append({
        'meta': {'stream': 'boost_pickups',
                 'timing': {'time': 4.12, 'frame': 184},
                 'primary_player': {'Epic': '222'}},
        'payload': {'payload': {
            'time': 4.12, 'pad_type': 'small',
            'player_position': [0.0, -4240.0, 86.4],
            'boost_before': 35.0, 'boost_after': 47.0,
        }},
    })
    result = normalize_subtr_replay(meta, arr, events)
    timeline = result['boostPadTimeline']
    assert timeline['source'] == 'native-boost-pickups'
    assert len(timeline['pads']) == 34
    assert timeline['observedPickupCount'] == 1
    assert timeline['unmatchedPickupCount'] == 0
    assert timeline['resets'] == [4.0]
    assert timeline['pickups'] == [{
        't': 4.12, 'padId': 6, 'playerId': 'Epic:222',
        'method': 'player_position_nearest',
    }]
    event = next(e for e in result['events'] if e['type'] == 'boost_pickups')
    assert event['nativeFrame'] == 184
    assert event['sampleIndex'] == 1
    assert event['padId'] == 6


def test_native_pickup_unknown_pad_does_not_create_false_state():
    meta, arr, events = fixture()
    events['events'].append({
        'meta': {'stream': 'boost_pickups', 'timing': {'time': 4.15}},
        'payload': {'payload': {'time': 4.15, 'pad_type': 'small',
                                'player_position': [9000, 9000, 86]}},
    })
    timeline = normalize_subtr_replay(meta, arr, events)['boostPadTimeline']
    assert timeline['observedPickupCount'] == 1
    assert timeline['unmatchedPickupCount'] == 1
    assert timeline['pickups'] == []
