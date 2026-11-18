from copy import deepcopy

import pytest

from coach_app.coaching import compact_game_states, find_review_candidates, suggested_support_point


def replay():
    players = [{'id': 'a', 'name': 'A', 'team': 'blue'}, {'id': 'b', 'name': 'B', 'team': 'blue'},
               {'id': 'c', 'name': 'C', 'team': 'orange'}, {'id': 'd', 'name': 'D', 'team': 'orange'}]
    fs = []
    for t in [0, 1, 30, 35, 65, 95]:
        defn = t >= 60
        fs.append({'t': t, 'ball': {'x': 0, 'y': -3600 if defn else 1000, 'z': 100}, 'cars': {
            'a': {'x': 0, 'y': -3850 if defn else 900, 'z': 17, 'boost': 5 if defn else 60},
            'b': {'x': 150, 'y': 900 if not defn else -200, 'z': 17, 'boost': 70},
            'c': {'x': 500, 'y': 1300, 'z': 17, 'boost': 50},
            'd': {'x': -500, 'y': 1400, 'z': 17, 'boost': 50},
        }})
    return {'schema': 'rl-coach/0.1', 'players': players, 'frames': fs, 'duration': 95}


def test_flags_are_review_candidates_not_certainties():
    r = replay()
    flags = find_review_candidates(r, 'a')
    assert any(f['type'] == 'overlap' for f in flags)
    assert any(f['type'] == 'boost' for f in flags)
    assert all(f['confidence'] == 'low' for f in flags)
    assert all(-3500 <= f['target']['x'] <= 3500 for f in flags)


def test_support_point_goal_side():
    b = {'x': 300, 'y': 0}
    assert suggested_support_point(b, 'blue', -400)['y'] < 0
    assert suggested_support_point(b, 'orange', -400)['y'] > 0


def test_compact_evidence_is_bounded_and_player_validated():
    r = replay()
    text = compact_game_states(r, 'a', max_frames=3)
    assert len(text.splitlines()) <= 7  # 4 header lines (incl. team roster) + 3 samples
    assert 'Players: P1=blue, P2=blue, P3=orange, P4=orange' in text
    assert 'Focus=P1 (blue)' in text
    assert 'Focus=a' not in text
    try:
        compact_game_states(r, 'not-there')
        assert False
    except ValueError:
        pass


def test_compact_review_never_exposes_platform_ids_including_extra_tracks():
    r = replay()
    mapping = {'a': 'account_id_A_private', 'b': 'account_id_B_private',
               'c': 'account_id_C_private', 'd': 'account_id_D_private'}
    for p in r['players']:
        p['id'] = mapping[p['id']]
    for frame in r['frames']:
        frame['cars'] = {mapping[pid]: car for pid, car in frame['cars'].items()}
    r['frames'][0]['cars']['unlisted_platform_ID_999'] = {
        'x': 0, 'y': 200, 'z': 17, 'boost': 20
    }
    summary = compact_game_states(r, mapping['a'], max_frames=3)
    assert 'Focus=P1 (blue)' in summary
    assert 'U1:' in summary
    assert not any(raw in summary for raw in list(mapping.values()) + ['unlisted_platform_ID_999'])


def test_selected_review_samples_only_predecision_window_and_keeps_final_frame():
    r = replay()
    template = r['frames'][2]
    r['frames'] = [dict(deepcopy(template), t=float(t))
                   for t in (0, 26, 27, 28, 29, 30, 31, 32, 90)]
    # A track that appears only later must never leak into the selected review.
    r['frames'][-1]['cars']['secret_future_platform_id'] = {
        'x': 999, 'y': 999, 'z': 17, 'boost': 60}
    text = compact_game_states(r, 'a', max_frames=2, selected_time=30.0)
    assert 'Pre-decision window: 27.00s through 30.00s' in text
    assert '27.0 |' in text
    assert '30.0 |' in text
    assert '26.0 |' not in text
    assert '31.0 |' not in text
    assert '90.0 |' not in text
    assert 'secret_future_platform_id' not in text
    assert 'U1:' not in text
    # Updating or removing ALL future data cannot change the evidence.
    trimmed = deepcopy(r)
    trimmed['frames'] = [f for f in trimmed['frames'] if f['t'] <= 30]
    assert compact_game_states(trimmed, 'a', max_frames=2, selected_time=30.0) == text


def test_selected_review_refuses_missing_or_stale_predecision_frames():
    r = replay()
    with pytest.raises(ValueError, match='recent pre-decision'):
        compact_game_states(r, 'a', selected_time=33.0)  # nearest sample is 30 s old by 3 s
    with pytest.raises(ValueError, match='finite'):
        compact_game_states(r, 'a', selected_time=float('nan'))
    with pytest.raises(ValueError, match='positive integer'):
        compact_game_states(r, 'a', max_frames=0, selected_time=30.0)
