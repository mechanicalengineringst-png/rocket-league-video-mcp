"""Counterexamples must not turn ordinary replay events into coaching verdicts."""
from copy import deepcopy

import pytest

from coach_app.contextual_review import build_contextual_reviews


def car(x, y, *, boost=60, vx=0, vy=0, z=17, forward=None):
    result = {'x': x, 'y': y, 'z': z, 'boost': boost, 'velocity': [vx, vy, 0]}
    if forward is not None:
        result['forward'] = forward
    return result


def fixture(actor='a', scene='shot'):
    if scene == 'shot':
        ball = {'x': 0, 'y': 2100, 'z': 100, 'velocity': [0, 350, 0]}
        cars = {
            'a': car(0, 1800, forward=[0, 1, 0]),
            'b': car(-1800, 900),
            'c': car(0, 4600, boost=4, vx=120),
            'd': car(2300, 3600),
        }
    elif scene == 'support':
        ball = {'x': 100, 'y': 1100, 'z': 105, 'velocity': [0, 150, 0]}
        cars = {
            'a': car(200, 800),
            'b': car(0, 1000),
            'c': car(350, 1450),
            'd': car(2400, 3400),
        }
    else:
        ball = {'x': 0, 'y': -3600, 'z': 120, 'velocity': [0, -1200, 0]}
        cars = {
            'a': car(0, -4200, boost=8),
            'b': car(1100, -2200),
            'c': car(50, -3480),
            'd': car(2300, 1600),
        }
    return {
        'source': 'subtr-actor-native-replay', 'playerMappingVerified': True,
        'players': [
            {'id': 'a', 'team': 'blue'}, {'id': 'b', 'team': 'blue'},
            {'id': 'c', 'team': 'orange'}, {'id': 'd', 'team': 'orange'},
        ],
        'frames': [{'t': t, 'ball': deepcopy(ball), 'cars': deepcopy(cars)} for t in [1.0, 1.35]],
        'events': [{'type': 'touch', 't': 1.0, 'playerId': actor}],
    }


def test_quick_shot_prompt_is_grounded_and_tentative():
    r = fixture()
    leads = build_contextual_reviews(r, 'a')
    assert len(leads) == 1
    assert leads[0]['kind'] == 'shot_window'
    assert '4 boost' in leads[0]['evidence']
    assert leads[0]['confidence'] == 'experimental'
    assert 'mechanically available' in leads[0]['advice']
    assert 'guarantee' in leads[0]['uncertainty']


def test_goalie_with_boost_or_momentum_does_not_trigger():
    for key, val in [('boost', 60), ('velocity', [1000, 0, 0])]:
        r = fixture()
        r['frames'][0]['cars']['c'][key] = val
        assert build_contextual_reviews(r, 'a') == []


def test_other_defender_near_shot_line_blocks_lead():
    r = fixture()
    r['frames'][0]['cars']['d']['x'] = 100
    assert build_contextual_reviews(r, 'a') == []


def test_no_forward_attitude_means_no_shot_advice():
    r = fixture()
    del r['frames'][0]['cars']['a']['forward']
    assert build_contextual_reviews(r, 'a') == []
    r['frames'][0]['cars']['a']['forward'] = [0, -1, 0]
    assert build_contextual_reviews(r, 'a') == []


def test_teammate_possession_and_compressed_support_trigger_question():
    r = fixture(actor='b', scene='support')
    leads = build_contextual_reviews(r, 'a')
    assert len(leads) == 1 and leads[0]['kind'] == 'second_man_support'
    assert 'recovery' in leads[0]['title'].lower()
    assert 'planned pass' in leads[0]['uncertainty']


def test_normal_50_and_goal_events_never_create_advice():
    r = fixture()
    r['events'] = [
        {'type': 'fifty_fifty', 't': n / 10, 'winningTeam': None} for n in range(50)
    ] + [{'type': 'goal_context', 't': 1.0, 'scoringTeam': 'blue'}]
    assert build_contextual_reviews(r, 'a') == []


def test_second_man_sufficiently_deep_or_no_pressure_is_not_flagged():
    r = fixture(actor='b', scene='support')
    r['frames'][0]['cars']['a']['y'] = 0
    assert build_contextual_reviews(r, 'a') == []
    r = fixture(actor='b', scene='support')
    r['frames'][0]['cars']['c']['x'] = 3800
    r['frames'][0]['cars']['c']['y'] = 3500
    assert build_contextual_reviews(r, 'a') == []


def test_defense_requires_pressure_movement_and_low_boost():
    r = fixture(actor='c', scene='defense')
    leads = build_contextual_reviews(r, 'a')
    assert len(leads) == 1 and leads[0]['kind'] == 'defensive_pressure'
    assert '8 boost' in leads[0]['evidence']
    x = fixture(actor='c', scene='defense')
    x['frames'][0]['cars']['a']['boost'] = 80
    assert build_contextual_reviews(x, 'a') == []
    x = fixture(actor='c', scene='defense')
    x['frames'][0]['ball']['velocity'] = [0, 1000, 0]
    assert build_contextual_reviews(x, 'a') == []


def test_kickoff_suppresses_all_contextual_verdicts():
    for actor, scene in [('a', 'shot'), ('b', 'support'), ('c', 'defense')]:
        r = fixture(actor=actor, scene=scene)
        r['events'].append({'type': 'kickoff', 't': 0})
        assert build_contextual_reviews(r, 'a') == []


def test_wrong_player_mapping_missing_identity_and_unknown_replays():
    r = fixture()
    r['playerMappingVerified'] = False
    assert build_contextual_reviews(r, 'a') == []
    r = fixture()
    r['source'] = 'synthetic'
    assert build_contextual_reviews(r, 'a') == []
    with pytest.raises(ValueError):
        build_contextual_reviews(r, 'missing')


def test_hindsight_events_do_not_change_predecision_candidate():
    r = fixture()
    a = build_contextual_reviews(r, 'a')
    r['events'].append({'type': 'goal_context', 't': 10.0, 'scoringTeam': 'orange'})
    r['events'].append({'type': 'fifty_fifty', 't': 2.0, 'winningTeam': 'orange'})
    assert build_contextual_reviews(r, 'a') == a


def test_identical_touches_are_deduplicated_and_count_is_bounded():
    r = fixture()
    r['events'] *= 40
    a = build_contextual_reviews(r, 'a')
    assert len(a) == 1
    assert a == build_contextual_reviews(r, 'a')
    with pytest.raises(ValueError):
        build_contextual_reviews(r, 'a', max_reviews=20)


def test_empty_and_corrupted_samples_fail_closed():
    r = fixture()
    r['frames'][0]['ball']['y'] = float('nan')
    assert build_contextual_reviews(r, 'a') == []
    r = fixture()
    r['frames'][1]['t'] = 0.0
    assert build_contextual_reviews(r, 'a') == []
