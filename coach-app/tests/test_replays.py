from types import SimpleNamespace

import pandas as pd
import pytest
from coach_app.replays import ReplayParseError, normalize_parsed_replay


def test_parsed_replay_normalizes_positions_and_boost():
    game = pd.DataFrame({'time':[0.0,0.25,0.5,1.0]}, index=[10,11,12,13])
    ball = pd.DataFrame({'pos_x':[0,20,50,100],'pos_y':[0,10,30,60], 'pos_z':[110]*4},index=[10,11,12,13])
    pa = pd.DataFrame({'pos_x':[0,100,200,300],'pos_y':[-1000,-900,-800,-700], 'pos_z':[17]*4,'boost_amount':[.5,.4,.3,.2]},index=[10,11,12,13])
    pb = pd.DataFrame({'pos_x':[0,0,0,0],'pos_y':[1000]*4,'pos_z':[17]*4,'boost_amount':[1.0]*4},index=[10,11,12,13])
    r=SimpleNamespace(game_df=game,ball_df=ball,player_dfs={'1':pa,'2':pb},metadata={'players':[{'unique_id':'1','name':'A','is_orange':False},{'unique_id':'2','name':'B','is_orange':True}]})
    result=normalize_parsed_replay(r, 'fixture')
    assert result['schema']=='rl-coach/0.1'
    assert result['mode']=='1v1'
    assert len(result['frames'])==3
    assert result['frames'][0]['cars']['1']['boost']==50
    assert result['frames'][-1]['ball']['x']==100
    assert result['players'][1]['team']=='orange'


def test_empty_timeline_rejected():
    r=SimpleNamespace(game_df=pd.DataFrame({'time':[]}),ball_df=pd.DataFrame(),player_dfs={},metadata={'players':[]})
    with pytest.raises(ReplayParseError):
        normalize_parsed_replay(r)
