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
    assert len(text.splitlines()) <= 6
    assert 'Focus=a' in text
    try:
        compact_game_states(r, 'not-there')
        assert False
    except ValueError:
        pass
