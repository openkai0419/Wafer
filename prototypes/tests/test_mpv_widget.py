import sys
import os
import types
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from PySide6 import QtCore, QtWidgets


sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

MOCK_MPV_MODULE = types.ModuleType('mpv')


class FakeMPV:
    def __init__(self, **kwargs):
        self._wid = kwargs.get('wid')
        self._playing = None
        self._event_callbacks = {}
        self._property_observers = {}
        self.volume = 100
        self.mute = False
        self.pause = False
        self.speed = 1.0
        self.duration = None
        self.time_pos = None
        self.path = None
        self._properties = {}

    def play(self, path):
        if self._playing is not None:
            self._fire_end_file()
        self._playing = path
        self.path = path

    def command(self, *args):
        pass

    def terminate(self):
        if self._playing is not None:
            self._fire_end_file()
        self._playing = None
        self.path = None

    def seek(self, amount, reference='relative'):
        pass

    def frame_step(self):
        pass

    def frame_back_step(self):
        pass

    def observe_property(self, name, handler):
        self._property_observers[name] = handler

    def event_callback(self, event_name):
        def decorator(fn):
            self._event_callbacks[event_name] = fn
            return fn
        return decorator

    def _fire_end_file(self):
        cb = self._event_callbacks.get('end-file')
        if cb:
            cb({'event': {'reason': 'eof'}})

    def _fire_eof_reached(self):
        handler = self._property_observers.get('eof-reached')
        if handler:
            handler('eof-reached', True)

    def __setitem__(self, key, value):
        self._properties[key] = value

    def __getitem__(self, key):
        return self._properties.get(key)


MOCK_MPV_MODULE.MPV = FakeMPV
sys.modules['mpv'] = MOCK_MPV_MODULE


from mpv_poc.test_embed import MpvWidget


@pytest.fixture
def widget(qtbot):
    w = MpvWidget()
    qtbot.addWidget(w)
    return w


class TestPlaylist:

    def test_set_playlist(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=1)
        assert widget._playlist == ['a.mp4', 'b.mp4', 'c.mp4']
        assert widget._playlist_index == 1
        assert widget.player.path == 'b.mp4'

    def test_set_playlist_empty(self, widget):
        widget.set_playlist([])
        assert widget._playlist == []
        assert widget._playlist_index == -1

    def test_load_single(self, widget):
        widget.load('x.mp4')
        assert widget._playlist == ['x.mp4']
        assert widget._playlist_index == 0
        assert widget.player.path == 'x.mp4'

    def test_play_index(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        widget.play_index(2)
        assert widget._playlist_index == 2
        assert widget.player.path == 'c.mp4'

    def test_play_index_out_of_range(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget.play_index(5)
        assert widget._playlist_index == 0

    def test_play_index_negative(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget.play_index(-1)
        assert widget._playlist_index == 0


class TestNavigation:

    def test_next_advances_by_one(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        widget.next_in_playlist()
        assert widget._playlist_index == 1
        assert widget.player.path == 'b.mp4'

    def test_next_wraps_around(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=2)
        widget.next_in_playlist()
        assert widget._playlist_index == 0
        assert widget.player.path == 'a.mp4'

    def test_prev_goes_back_by_one(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=2)
        widget.prev_in_playlist()
        assert widget._playlist_index == 1
        assert widget.player.path == 'b.mp4'

    def test_prev_wraps_around(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        widget.prev_in_playlist()
        assert widget._playlist_index == 2
        assert widget.player.path == 'c.mp4'

    def test_next_on_empty_playlist(self, widget):
        widget.next_in_playlist()
        assert widget._playlist_index == -1

    def test_prev_on_empty_playlist(self, widget):
        widget.prev_in_playlist()
        assert widget._playlist_index == -1

    def test_consecutive_next(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4', 'd.mp4'], start_index=0)
        widget.next_in_playlist()
        assert widget._playlist_index == 1
        widget.next_in_playlist()
        assert widget._playlist_index == 2
        widget.next_in_playlist()
        assert widget._playlist_index == 3

    def test_next_does_not_double_advance(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        widget.next_in_playlist()
        assert widget._playlist_index == 1, 'next should advance by exactly 1'
        assert widget.player.path == 'b.mp4'


class TestTransitioning:

    def test_transitioning_set_on_play_current(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        assert widget._transitioning is True

    def test_next_sets_transitioning(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget._transitioning = False
        widget.next_in_playlist()
        assert widget._transitioning is True

    def test_prev_sets_transitioning(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget._transitioning = False
        widget.prev_in_playlist()
        assert widget._transitioning is True

    def test_play_index_sets_transitioning(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        widget._transitioning = False
        widget.play_index(2)
        assert widget._transitioning is True

    def test_stop_sets_transitioning(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget._transitioning = False
        widget.stop()
        assert widget._transitioning is True

    def test_handle_end_file_transitioning_clears_flag(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget._transitioning = True
        widget._handle_end_file()
        assert widget._transitioning is False
        assert widget._playlist_index == 0

    def test_handle_end_file_not_transitioning_does_nothing(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        widget._transitioning = False
        widget._handle_end_file()
        assert widget._playlist_index == 0

    def test_eof_sets_transitioning_during_loop(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget.set_loop(True)
        widget._transitioning = False
        widget._handle_eof()
        assert widget._transitioning is True
        assert widget._playlist_index == 0


class TestStop:

    def test_stop_does_not_advance(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        widget.stop()
        assert widget._playlist_index == 0

    def test_stop_then_next_advances_by_one(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        widget.stop()
        widget.next_in_playlist()
        assert widget._playlist_index == 1


class TestLoop:

    def test_loop_replays_same_file(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget.set_loop(True)
        widget._transitioning = False
        widget._handle_eof()
        assert widget._playlist_index == 0

    def test_loop_off_auto_advances(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget.set_loop(False)
        widget.set_auto_play(True)
        widget._transitioning = False
        widget._handle_eof()
        assert widget._playlist_index == 1

    def test_loop_toggle(self, widget):
        widget.set_loop(True)
        assert widget._loop is True
        widget.set_loop(False)
        assert widget._loop is False

    def test_loop_priority_over_auto_play(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget.set_loop(True)
        widget.set_auto_play(True)
        widget._transitioning = False
        widget._handle_eof()
        assert widget._playlist_index == 0

    def test_eof_via_fake_mpv(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        widget.set_loop(True)
        widget._transitioning = False
        widget.player._fire_eof_reached()
        assert widget._playlist_index == 0


class TestAutoPlay:

    def test_auto_play_advances_on_eof(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        widget.set_auto_play(True)
        widget.set_loop(False)
        widget._transitioning = False
        widget._handle_eof()
        assert widget._playlist_index == 1

    def test_auto_play_off_stays(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        widget.set_auto_play(False)
        widget.set_loop(False)
        widget._transitioning = False
        widget._handle_eof()
        assert widget._playlist_index == 0

    def test_auto_play_wraps_around(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=1)
        widget.set_auto_play(True)
        widget.set_loop(False)
        widget._transitioning = False
        widget._handle_eof()
        assert widget._playlist_index == 0

    def test_auto_play_single_file_no_advance(self, widget):
        widget.set_playlist(['a.mp4'], start_index=0)
        widget.set_auto_play(True)
        widget.set_loop(False)
        widget._transitioning = False
        widget._handle_eof()
        assert widget._playlist_index == 0

    def test_set_auto_play(self, widget):
        widget.set_auto_play(False)
        assert widget._auto_play is False
        widget.set_auto_play(True)
        assert widget._auto_play is True


class TestVolumeRetention:

    def test_volume_persists_after_stop(self, widget):
        widget.set_playlist(['a.mp4'], start_index=0)
        widget.set_volume(42)
        widget.set_mute(True)
        widget.stop()
        assert widget.player is None
        assert widget._volume == 42
        assert widget._mute is True

    def test_volume_restored_on_next_play(self, widget):
        widget.set_volume(42)
        widget.set_mute(True)
        widget.set_playlist(['a.mp4'], start_index=0)
        assert widget.player.volume == 42
        assert widget.player.mute is True

    def test_set_volume_updates_player(self, widget):
        widget.set_playlist(['a.mp4'], start_index=0)
        widget.set_volume(75)
        assert widget.player.volume == 75
        assert widget._volume == 75

    def test_set_volume_without_player(self, widget):
        widget.set_volume(60)
        assert widget._volume == 60
        assert widget.player is None

    def test_set_mute_updates_player(self, widget):
        widget.set_playlist(['a.mp4'], start_index=0)
        widget.set_mute(True)
        assert widget.player.mute is True
        assert widget._mute is True


class TestSignals:

    def test_file_started_emitted_on_load(self, widget):
        received = []
        widget.file_started.connect(lambda p: received.append(p))
        widget.load('test.mp4')
        assert received == ['test.mp4']

    def test_file_started_emitted_on_next(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        received = []
        widget.file_started.connect(lambda p: received.append(p))
        widget.next_in_playlist()
        assert received == ['b.mp4']

    def test_file_started_emitted_on_play_index(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4', 'c.mp4'], start_index=0)
        received = []
        widget.file_started.connect(lambda p: received.append(p))
        widget.play_index(2)
        assert received == ['c.mp4']

    def test_file_ended_emitted_on_natural_eof(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        received = []
        widget.file_ended.connect(lambda p: received.append(p))
        widget._transitioning = False
        widget._handle_eof()
        assert received == ['a.mp4']

    def test_file_ended_not_emitted_when_transitioning(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        received = []
        widget.file_ended.connect(lambda p: received.append(p))
        widget._transitioning = True
        widget._handle_eof()
        assert received == []

    def test_file_ended_not_emitted_by_end_file(self, widget):
        widget.set_playlist(['a.mp4', 'b.mp4'], start_index=0)
        received = []
        widget.file_ended.connect(lambda p: received.append(p))
        widget._transitioning = True
        widget._handle_end_file()
        assert received == []
        widget._handle_end_file()
        assert received == []


class TestFitMode:

    def test_fit_mode_cover(self, widget):
        widget.set_playlist(['a.mp4'], start_index=0)
        widget.set_fit_mode(True)
        assert widget.player['panscan'] == 1.0
        assert widget._panscan == 1.0

    def test_fit_mode_fit(self, widget):
        widget.set_playlist(['a.mp4'], start_index=0)
        widget.set_fit_mode(False)
        assert widget.player['panscan'] == 0.0
        assert widget._panscan == 0.0

    def test_fit_mode_without_player(self, widget):
        widget.set_fit_mode(True)
        assert widget._panscan == 1.0
        assert widget.player is None


class TestLazyInit:

    def test_player_none_on_init(self, widget):
        assert widget.player is None

    def test_player_created_on_play(self, widget):
        widget.load('a.mp4')
        assert widget.player is not None

    def test_player_destroyed_on_stop(self, widget):
        widget.load('a.mp4')
        assert widget.player is not None
        widget.stop()
        assert widget.player is None

    def test_player_recreated_on_next_play(self, widget):
        widget.load('a.mp4')
        widget.stop()
        assert widget.player is None
        widget.load('b.mp4')
        assert widget.player is not None
        assert widget.player.path == 'b.mp4'

    def test_speed_restored_on_recreate(self, widget):
        widget.set_speed(2.0)
        widget.load('a.mp4')
        assert widget.player.speed == 2.0

    def test_panscan_restored_on_recreate(self, widget):
        widget.set_fit_mode(True)
        widget.load('a.mp4')
        assert widget.player['panscan'] == 1.0

    def test_duration_none_without_player(self, widget):
        assert widget.duration is None

    def test_time_pos_none_without_player(self, widget):
        assert widget.time_pos is None

    def test_stop_without_player_safe(self, widget):
        widget.stop()
        assert widget.player is None

    def test_seek_without_player_safe(self, widget):
        widget.seek(10)
        widget.seek_absolute(5)
        widget.frame_step()
        widget.frame_back_step()

    def test_toggle_pause_without_player_safe(self, widget):
        widget.toggle_pause()
