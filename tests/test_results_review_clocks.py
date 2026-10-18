import io
import json
import logging
import zipfile
import chess
import chess.pgn
import numpy as np
import pytest
from chessstream.domain import Observation,Settings,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store
from chessstream.results import EndMessage,EndMessageDetector,parse_end_message,clock_seconds,extract_context,ContextStabilizer
from chessstream.diagnostics import configure_logging,export_diagnostics


def test_end_text_maps_scores_colors_abandonment_and_aborted_without_inventing_winner():
    def parse(text,color=None):return parse_end_message([(text,.98)],color)
    assert parse('You Won! Game abandoned','black').result=='0-1'
    assert parse('YouWon! GameAbandoned','black').result=='0-1'
    assert parse('0 - 1').result=='0-1'
    assert parse('0–1').result=='0-1'
    assert parse('You Lost on time','white').result=='0-1'
    assert parse('Black won by resignation').result=='0-1'
    assert parse('Game over 1 - 0').result=='1-0'
    assert parse('Draw 1/2-1/2').result=='1/2-1/2'
    assert parse('Game Aborted').result=='*'
    assert parse('You Won! Game abandoned').result=='*'
    assert parse('9:59') is None
    assert parse('New game 10 min') is None
    assert parse_end_message([('You Won!',.5)],'white') is None


def test_result_requires_repeated_evidence_and_lost_text_resets_debounce():
    class Reader:
        text='You Won!'
        def read(self,image):return [(self.text,.99)] if self.text else []
    now=[0.];reader=Reader();detector=EndMessageDetector(reader,lambda:now[0]);image=np.zeros((10,10,3),np.uint8)
    assert detector.scan(image,'black') is None
    now[0]=1.1
    assert detector.scan(image,'black').result=='0-1'
    now[0]=2.2;reader.text='';image[0,0]=1
    assert detector.scan(image,'black') is None
    now[0]=3.3;reader.text='You Won!';image[0,0]=2
    assert detector.scan(image,'black') is None


def game_with_pending(store):
    manager=GameManager(store,Settings())
    board=chess.Board();manager.process(Observation.from_board(board))
    for san in ['e4','e5','Nf3']:
        board.push_san(san);manager.process(Observation.from_board(board))
    return manager,board


def test_terminal_message_confirms_only_supported_final_move_then_freezes_mainline(tmp_path):
    store=Store(tmp_path);manager,board=game_with_pending(store)
    assert len(manager.rec.verified)==2
    popup=Observation.from_board(board);popup.probabilities[chess.D4]=1/13
    manager.rec.incomplete=True
    assert manager.declare_end(EndMessage('0-1','abandoned','You Won! Game abandoned',.98),popup)
    assert len(manager.rec.verified)==3
    assert manager.headers['Result']=='0-1'
    gid=manager.current_id
    board.push_san('Nc6');manager.process(Observation.from_board(board))
    assert len(manager.rec.verified)==3 and manager.current_id==gid
    manager.process(Observation.from_board(chess.Board()))
    assert manager.current_id!=gid and store.game(gid)['ended']
    assert chess.pgn.read_game(io.StringIO(store.game(gid)['pgn'])).headers['Result']=='0-1'
    store.close()


def test_result_does_not_certify_hidden_destination_but_clear_later_board_can(tmp_path):
    store=Store(tmp_path);manager,board=game_with_pending(store)
    popup=Observation.from_board(board);popup.probabilities[chess.F3]=1/13
    manager.declare_end(EndMessage('1-0','game ended','White won',.99),popup)
    assert len(manager.rec.verified)==2
    manager.process(Observation.from_board(board))
    assert len(manager.rec.verified)==3
    store.close()


def test_variations_comments_clocks_survive_edit_export_and_restart(tmp_path):
    store=Store(tmp_path);manager,board=game_with_pending(store);manager.choose(0);gid=manager.current_id
    mainline=manager.rec.verified[:]
    manager.annotate(gid,[],'d4 d5 c4','A different opening')
    manager.annotate(gid,[1,0],'Nf3','Nested branch')
    parsed=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
    assert parsed.variations[0].move.uci()=='e2e4'
    assert parsed.variations[1].variations[0].variations[1].move.uci()=='g1f3'
    assert parsed.variations[1].variations[0].variations[1].comment=='Nested branch'
    with pytest.raises(ValueError):manager.annotate(gid,[0,0,0],'Nc6')
    manager.move_clocks={'1':599.,'2':598.4};manager.persist()
    manager.edit(gid,'Renamed',{**manager.headers,'Event':'Review test'})
    manager.recover(gid)
    parsed=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
    assert len(parsed.variations)==2 and parsed.variations[0].clock()==599
    assert parsed.variations[0].variations[0].clock()==598.4
    assert manager.rec.verified==mainline
    manager.annotate(gid,[1],delete=True)
    assert len(chess.pgn.read_game(io.StringIO(store.game(gid)['pgn'])).variations)==1
    store.close()


def test_observed_clock_is_attached_to_move_when_later_confirmed(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());board=chess.Board()
    manager.process(Observation.from_board(board))
    board.push_san('e4');obs=Observation.from_board(board)
    manager.observe_context({'clocks':{'white':599,'black':600},'names':{}},obs.timestamp);manager.process(obs)
    assert not manager.rec.verified
    board.push_san('e5');obs=Observation.from_board(board)
    manager.observe_context({'clocks':{'white':599,'black':597},'names':{}},obs.timestamp);manager.process(obs)
    parsed=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert parsed.variations[0].clock()==599
    manager.choose(0)
    parsed=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert parsed.variations[0].variations[0].clock()==597
    store.close()


def test_names_clocks_spatial_assignment_and_stable_identity_change(tmp_path):
    assert clock_seconds('9:59')==599
    assert clock_seconds('1:02:03')==3723
    assert clock_seconds('0:04.5')==4.5
    lines=[('Opponent (492):',.99,(80,5,160,25)),('9:59',.99,(350,5,400,25)),('Streamer',.99,(80,465,160,485)),('4:30',.99,(350,465,400,485)),('e4',.99,(120,220,160,240))]
    context=extract_context(lines,(50,40,400,400),'black')
    assert context=={'clocks':{'white':599,'black':270},'names':{'white':'Opponent','black':'Streamer'}}
    stable=ContextStabilizer();assert not stable.observe(context)['names'];assert not stable.observe(context)['names']
    assert stable.observe(context)['names']==context['names']
    store=Store(tmp_path);manager=GameManager(store,Settings());board=chess.Board();manager.process(Observation.from_board(board));gid=manager.current_id
    manager.observe_context(context,utcnow());assert manager.headers['Black']=='Streamer'
    manager.observe_context({**context,'names':{'white':'NewOpponent','black':'Streamer'}},utcnow())
    manager.process(Observation.from_board(board))
    assert manager.current_id!=gid and manager.headers['White']=='NewOpponent'
    assert json.loads(store.game(gid)['headers'])['White']=='Opponent'
    store.close()


def test_diagnostics_bundle_contains_status_and_pgn_but_no_screenshots(tmp_path):
    configure_logging(tmp_path);store=Store(tmp_path);manager,board=game_with_pending(store)
    logging.warning('Recognition warning for support')
    bundle=tmp_path/'support.zip';export_diagnostics(store,bundle)
    with zipfile.ZipFile(bundle) as archive:
        assert 'Recognition warning for support' in archive.read('logs/application.log').decode()
        report=json.loads(archive.read('diagnostics.json'))
        assert report['observations'] and report['games']
        assert any(n.startswith('pgn/') for n in archive.namelist())
        assert not any(n.endswith('.png') for n in archive.namelist())
    store.close()


def test_aborted_before_first_move_arms_new_standard_game(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());manager.process(Observation.from_board(chess.Board()));gid=manager.current_id
    manager.declare_end(EndMessage('*','aborted','Game Aborted',.99))
    board=chess.Board();board.push_san('e4');manager.process(Observation.from_board(board))
    assert manager.current_id!=gid and manager.terminal_message is None
    assert manager.snapshot()['pending_moves']==['e4']
    store.close()


def test_postgame_analysis_is_a_variation_and_cannot_extend_played_mainline(tmp_path):
    store=Store(tmp_path);manager,board=game_with_pending(store)
    manager.declare_end(EndMessage('1-0','game ended','White Won',.99),Observation.from_board(board));played=manager.rec.verified[:]
    analysis=chess.Board();analysis.push_san('e4');manager.process(Observation.from_board(analysis))
    analysis.push_san('c5');manager.process(Observation.from_board(analysis))
    analysis.push_san('Nf3');manager.process(Observation.from_board(analysis))
    pgn=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert manager.rec.verified==played
    assert len(pgn.variations[0].variations)==2
    assert pgn.variations[0].variations[1].move.uci()=='c7c5'
    assert pgn.headers['Result']=='1-0'
    store.close()


def test_real_chesscom_captured_clocks_names_and_native_result_messages():
    from pathlib import Path
    import cv2
    from chessstream.results import LocalTextReader
    from chessstream.vision import ScreenshotRecognizer,BoardDetector
    root=Path(__file__).parent/'fixtures/results';reader=LocalTextReader();recognizer=ScreenshotRecognizer()
    for name,result in [('native-bot-resigned.png','0-1'),('native-bot-aborted.png','*')]:
        image=cv2.imread(str(root/name));lines=reader.read(image)
        context=extract_context(lines,(108,66,568,568),'white')
        assert context['names']=={'black':'Martinfoot','white':'Guest'}
        assert all(500<=value<=600 for value in context['clocks'].values())
        message=parse_end_message(lines,'white',context['names'])
        assert message and message.result==result
    image=cv2.imread(str(root/'native-bot-clock.png'))
    board=chess.Board();board.push_san('e4');board.push_san('c5')
    assert recognizer.recognize(image[66:634,108:676]).placement()==board.board_fen()
    start=cv2.imread(str(root/'native-bot-start.png'));rect,_=BoardDetector().detect(start)
    assert rect is not None
    x,y,w,h=rect
    assert recognizer.recognize(start[y:y+h,x:x+w]).placement()==chess.Board().board_fen()


def test_reported_d6_with_abandonment_popup_commits_despite_other_obscured_squares(tmp_path):
    board=chess.Board()
    for san in 'e4 e5 Nf3 Nc6 Bc4 Bc5 d4 Bxd4 c3 Bb6 Ng5 Nh6 Qf3 O-O Qh5'.split():board.push_san(san)
    store=Store(tmp_path);manager=GameManager(store,Settings(initial_fen=board.fen()))
    initial=Observation.from_board(board);initial.orientation='black';manager.process(initial)
    board.push_san('d6');manager.process(Observation.from_board(board))
    assert manager.snapshot()['pending_moves']==['d6']
    overlay=Observation.from_board(board)
    for square in [chess.C4,chess.D4,chess.F6]:overlay.probabilities[square]=1/13
    manager.rec.incomplete=True
    message=parse_end_message([('You Won!',.99),('Game abandoned',.99)],manager.result_player())
    manager.declare_end(message,overlay)
    parsed=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert parsed.headers['Result']=='0-1'
    assert parsed.board().san(next(iter(parsed.mainline_moves())))=='d6'
    assert manager.snapshot()['moves']==['d6']
    store.close()
