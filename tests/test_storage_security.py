"""Retention, PGN independence and exploitable input boundaries."""
import numpy as np
import pytest
from chessstream.domain import Settings,Observation,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store
from chessstream.model_security import validate_bgr_image,validate_custom_model,verify_bundled_model,BUNDLED_MODEL_SHA256
from chessstream.vision import ASSETS
from security.paddlex_safe_scale import parse_scale_expression
import chess


def test_position_storage_survives_resize_and_retention_leaves_game_and_pgn_independent(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());board=chess.Board()
    manager.process(Observation.from_board(board));gid,sid=manager.current_id,manager.session_id
    image=np.zeros((80,80,3),np.uint8);old='2025-01-01T00:00:00.000+00:00'
    assert store.save_screenshot(sid,gid,image,old,board.board_fen(),deduplicate_position=True)
    assert store.save_screenshot(sid,gid,image,old,None)
    manager.force_new()
    assert store.save_screenshot(sid,manager.current_id,np.ones((160,160,3),np.uint8),utcnow(),board.board_fen(),deduplicate_position=True) is None
    board.push_san('e4')
    assert store.save_screenshot(sid,gid,image,utcnow(),board.board_fen(),deduplicate_position=True)
    store.schedule_deletion('2025-02-01T00:00:00+00:00',{'before':'2025-02-01T00:00:00+00:00'})
    store.close();store=Store(tmp_path)
    assert store.run_retention()[0]['count']==2 and len(store.screenshots())==1
    assert store.game(gid) and (tmp_path/'pgn'/f'{gid}.pgn').exists()
    store.delete_pgn_files([gid]);assert store.game(gid) and len(store.screenshots())==1
    with pytest.raises(ValueError):store.screenshot_file('../settings.json')
    store.close()


def test_safe_scale_parser_accepts_numeric_scales_and_rejects_inert_attack_and_invalid_syntax(tmp_path):
    assert parse_scale_expression('1./255.')==1/255
    marker=tmp_path/'must-not-exist'
    for expression in [f"__import__('pathlib').Path({str(marker)!r}).touch()",'(1).__class__','[1][0]','1/0','1e999','1 ** 2']:
        with pytest.raises(ValueError):parse_scale_expression(expression)
    assert not marker.exists()


def test_models_and_image_decoding_keep_integrity_path_and_resource_boundaries(tmp_path):
    models=ASSETS/'models'
    for name in BUNDLED_MODEL_SHA256:assert verify_bundled_model(models/name,models).is_file()
    tampered=tmp_path/'chess-tiles-v2.onnx';tampered.write_bytes(b'not the trusted model')
    with pytest.raises(RuntimeError):verify_bundled_model(tampered,tmp_path)
    with pytest.raises(ValueError):validate_custom_model(r'\\server\share\model.onnx')
    with pytest.raises(ValueError):validate_bgr_image(np.zeros((80,80),np.uint8))
    huge=np.lib.stride_tricks.as_strided(np.zeros((1,1,3),np.uint8),shape=(8193,8193,3),strides=(0,0,1),writeable=False)
    with pytest.raises(ValueError):validate_bgr_image(huge)


def test_selected_screenshot_ids_delete_only_images_and_keep_pgn(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());board=chess.Board()
    manager.process(Observation.from_board(board));gid,sid=manager.current_id,manager.session_id
    image=np.zeros((80,80,3),np.uint8)
    ids=[store.save_screenshot(sid,gid,image,f'2026-10-19T00:00:0{i}.000+00:00',board.board_fen()) for i in (1,2,3)]
    result=store.delete_screenshots({'ids':ids[:2]})
    assert result['count']==2 and len(store.screenshots())==1
    assert store.game(gid) and (tmp_path/'pgn'/f'{gid}.pgn').exists()
    with pytest.raises(ValueError):store.screenshot_filter({'ids':[0]})
    store.close()
