#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""무한 음악 플레이어 — 안드로이드(Kivy) 버전.

데스크톱 버전(music-player)의 소스/가사/검색 로직을 재사용하고,
재생은 안드로이드 별도 프로세스(포그라운드 서비스)에서 Native MediaPlayer 로
수행한다. 덕분에 화면을 나가도/앱을 닫아도 음악이 계속 재생된다.
"""
from __future__ import annotations

import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from mplayer import config  # noqa: E402
config.ensure_dirs()
config.setup_tls()

from kivy.app import App                                  # noqa: E402
from kivy.clock import Clock                              # noqa: E402
from kivy.core.text import LabelBase, DEFAULT_FONT        # noqa: E402
from kivy.graphics import Color, RoundedRectangle, Rectangle  # noqa: E402
from kivy.metrics import dp, sp                           # noqa: E402
from kivy.uix.boxlayout import BoxLayout                  # noqa: E402
from kivy.uix.button import Button                        # noqa: E402
from kivy.uix.floatlayout import FloatLayout              # noqa: E402
from kivy.uix.image import Image as KvImage               # noqa: E402
from kivy.uix.label import Label as _KivyLabel            # noqa: E402
from kivy.uix.scrollview import ScrollView                # noqa: E402
from kivy.uix.screenmanager import (ScreenManager, Screen,  # noqa: E402
                                     NoTransition)
from kivy.uix.spinner import Spinner, SpinnerOption      # noqa: E402
from kivy.uix.slider import Slider                        # noqa: E402
from kivy.uix.switch import Switch                        # noqa: E402

from mplayer import chart as chart_mod                    # noqa: E402
from mplayer import lyrics as lyrics_mod                  # noqa: E402
from mplayer.downloader import Downloader                 # noqa: E402
from mplayer.models import Track                          # noqa: E402
from mplayer.service_client import ServiceClient          # noqa: E402
from mplayer.sources import SOURCES                       # noqa: E402

# ---------------------------------------------------------------------------
# 폰트 (한글 렌더링에 필요)
# ---------------------------------------------------------------------------
FONT_R = os.path.join(_HERE, "assets", "NanumGothic-Regular.ttf")
FONT_B = os.path.join(_HERE, "assets", "NanumGothic-Bold.ttf")
if os.path.exists(FONT_R):
    LabelBase.register(DEFAULT_FONT, fn_regular=FONT_R,
                       fn_bold=FONT_B if os.path.exists(FONT_B) else FONT_R)

# ---------------------------------------------------------------------------
# 테마
# ---------------------------------------------------------------------------
def C(h, a=1.0):
    return (int(h[1:3], 16) / 255.0, int(h[3:5], 16) / 255.0,
            int(h[5:7], 16) / 255.0, a)


PAGE = C("#12161d")
CARD = C("#1e2430")
HEADER = C("#0e1420")
NAV = C("#141922")
FG = C("#e8eef6")
MUTED = C("#93a1b2")
LINE = C("#2c3542")
ACCENT = C("#6fb2ff")
FIELD = C("#2b3546")
HIST = C("#171c25")
GREEN = C("#2f9e5f")
RED = C("#e74c3c")
ORANGE = C("#f39c12")


# ---------------------------------------------------------------------------
# 공통 위젯
# ---------------------------------------------------------------------------
class Lbl(_KivyLabel):
    """위젯 크기에 맞춰 text_size 를 잡는 라벨."""

    def __init__(self, **kw):
        kw.pop("text_size", None)
        super().__init__(**kw)
        self.bind(size=self._fit)
        self._fit()

    def _fit(self, *a):
        self.text_size = (self.width, self.height)


class Card(BoxLayout):
    def __init__(self, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("padding", dp(10))
        kw.setdefault("spacing", dp(6))
        kw.setdefault("size_hint_y", None)
        super().__init__(**kw)
        self._c = Color(*CARD)
        self._r = RoundedRectangle(radius=[dp(12)])
        self.canvas.before.add(self._c)
        self.canvas.before.add(self._r)
        self.bind(pos=self._sync, size=self._sync)
        self._sync()

    def _sync(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size


class FlatButton(Button):
    bg = [0.17, 0.21, 0.27, 1]

    def __init__(self, **kw):
        kw.setdefault("background_normal", "")
        kw.setdefault("background_down", "")
        kw.setdefault("background_color", (0, 0, 0, 0))
        kw.setdefault("font_size", sp(13))
        kw.setdefault("color", FG)
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(44))
        super().__init__(**kw)
        self._c = Color(*self.bg)
        self._r = RoundedRectangle(radius=[dp(10)])
        self.canvas.before.add(self._c)
        self.canvas.before.add(self._r)
        self.bind(pos=self._sync, size=self._sync, bg=self._sync, state=self._sync)
        self._sync()

    def _sync(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size

    def _sync_state(self, *a):
        c = list(self.bg)
        if self.state == "down":
            c = [max(0, v * 0.72) for v in c[:3]] + [c[3]]
        self._c.rgba = c

    def _sync(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size
        self._sync_state()


class IconButton(FlatButton):
    """재생/일시정지 같은 큰 버튼."""

    def __init__(self, **kw):
        kw.setdefault("font_size", sp(18))
        kw.setdefault("height", dp(56))
        kw.setdefault("size_hint_x", None)
        kw.setdefault("width", dp(84))
        super().__init__(**kw)


class TrackRow(BoxLayout):
    """차트 목록 한 줄."""

    def __init__(self, app, track, **kw):
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(52))
        kw.setdefault("spacing", dp(8))
        kw.setdefault("padding", (dp(8), 0))
        super().__init__(**kw)
        self._c = Color(*HIST)
        self._r = RoundedRectangle(radius=[dp(8)])
        self.canvas.before.add(self._c)
        self.canvas.before.add(self._r)
        self.bind(pos=self._sync, size=self._sync)
        self.add_widget(Lbl(text=str(track.rank or "-"), color=MUTED,
                            font_size=sp(12), size_hint_x=None, width=dp(24),
                            halign="center"))
        info = BoxLayout(orientation="vertical")
        info.add_widget(Lbl(text=track.title, color=FG, font_size=sp(12.5),
                            halign="left"))
        sub = track.artist or track.source
        info.add_widget(Lbl(text=sub, color=MUTED, font_size=sp(10),
                            halign="left"))
        self.add_widget(info)
        self.add_widget(Lbl(text="▶", color=ACCENT, font_size=sp(15),
                            size_hint_x=None, width=dp(30), halign="center"))
        self.bind(on_release=lambda *a: app.play_track(track))
        self._sync()

    def _sync(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
class BaseScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        root = BoxLayout(orientation="vertical")
        self.box = BoxLayout(orientation="vertical", size_hint_y=None,
                             spacing=dp(8), padding=(0, dp(2)))
        self.box.bind(minimum_height=self.box.setter("height"))
        sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
        sv.add_widget(self.box)
        root.add_widget(sv)
        self.add_widget(root)

    def section(self, title):
        card = Card()
        card.add_widget(Lbl(text=title, color=FG, bold=True, font_size=sp(12.5),
                            halign="left", valign="middle", text_size=(None, None)))
        self.box.add_widget(card)
        return card


class ChartScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="chart", **kw)
        card = Card()
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(42),
                        spacing=dp(6))
        self.sp_source = Spinner(text=SOURCES[0].label, values=[s.label for s in SOURCES],
                                 size_hint_y=None, height=dp(40), font_size=sp(12),
                                 background_normal="", background_down="",
                                 background_color=FIELD, color=FG)
        btn = FlatButton(text="불러오기", bg=ACCENT, color=PAGE)
        btn.bind(on_release=lambda *a: self.app.load_chart())
        row.add_widget(self.sp_source)
        row.add_widget(btn)
        card.add_widget(row)
        self.box.add_widget(card)

        self.list_card = Card()
        self.list_holder = BoxLayout(orientation="vertical", size_hint_y=None,
                                      spacing=dp(4))
        self.list_holder.bind(minimum_height=self.list_holder.setter("height"))
        self.list_card.add_widget(self.list_holder)
        self.box.add_widget(self.list_card)

    def selected_source(self):
        label = self.sp_source.text
        for s in SOURCES:
            if s.label == label:
                return s
        return SOURCES[0]

    def set_tracks(self, tracks):
        self.list_holder.clear_widgets()
        if not tracks:
            self.list_holder.add_widget(Lbl(text="불러오기를 눌러 차트를 가져오세요.",
                                            color=MUTED, font_size=sp(12), halign="left"))
            return
        for t in tracks:
            self.list_holder.add_widget(TrackRow(self.app, t))


class PlayerScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="player", **kw)
        card = Card()
        art_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(120),
                            spacing=dp(10))
        self.art = KvImage(size_hint_x=None, width=dp(110), allow_stretch=True,
                           keep_ratio=True, color=(1, 1, 1, 1))
        art_row.add_widget(self.art)
        info = BoxLayout(orientation="vertical", spacing=dp(4))
        self.lbl_title = Lbl(text="재생할 곡이 없습니다", color=FG, bold=True,
                             font_size=sp(14), halign="left", valign="bottom")
        self.lbl_artist = Lbl(text="", color=MUTED, font_size=sp(11.5), halign="left")
        self.lbl_status = Lbl(text="", color=ORANGE, font_size=sp(10.5), halign="left")
        info.add_widget(self.lbl_title)
        info.add_widget(self.lbl_artist)
        info.add_widget(self.lbl_status)
        art_row.add_widget(info)
        card.add_widget(art_row)

        prog = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(22),
                         spacing=dp(6))
        self.sld_pos = Slider(min=0, max=100, value=0, size_hint_x=1,
                              cursor_size=(dp(22), dp(22)))
        self.sld_pos.bind(value=lambda *a: None)
        self.lbl_time = Lbl(text="0:00", color=MUTED, font_size=sp(10),
                            size_hint_x=None, width=dp(42), halign="right")
        prog.add_widget(self.sld_pos)
        prog.add_widget(self.lbl_time)
        card.add_widget(prog)

        ctrl = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(62),
                         spacing=dp(8))
        b_prev = IconButton(text="⏮", bg=FIELD)
        b_prev.bind(on_release=lambda *a: self.app.cmd("prev"))
        self.b_play = IconButton(text="▶", bg=GREEN)
        self.b_play.bind(on_release=lambda *a: self.app.cmd("toggle"))
        b_next = IconButton(text="⏭", bg=FIELD)
        b_next.bind(on_release=lambda *a: self.app.cmd("next"))
        ctrl.add_widget(b_prev)
        ctrl.add_widget(b_play)
        ctrl.add_widget(b_next)
        card.add_widget(ctrl)

        vol = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(34),
                        spacing=dp(6))
        vol.add_widget(Lbl(text="🔈", color=MUTED, font_size=sp(12),
                           size_hint_x=None, width=dp(28)))
        self.sld_vol = Slider(min=0, max=100, value=80, size_hint_x=1,
                               cursor_size=(dp(20), dp(20)))
        self.sld_vol.bind(value=self._on_volume)
        vol.add_widget(self.sld_vol)
        self.lbl_vol = Lbl(text="80%", color=MUTED, font_size=sp(10),
                           size_hint_x=None, width=dp(42), halign="right")
        vol.add_widget(self.lbl_vol)
        card.add_widget(vol)
        self.box.add_widget(card)

        # 노래방 가사
        lyric_card = Card()
        lyric_card.add_widget(Lbl(text="노래방 가사", color=FG, bold=True,
                                  font_size=sp(12.5), halign="left",
                                  valign="middle", text_size=(None, None)))
        self.lbl_lyric = Lbl(text="", color=ACCENT, font_size=sp(17), bold=True,
                             halign="center", valign="middle", text_size=(None, None),
                             size_hint_y=None, height=dp(70))
        lyric_card.add_widget(self.lbl_lyric)
        self.lyric_scroll = ScrollView(do_scroll_x=False, bar_width=dp(2),
                                       size_hint_y=None, height=dp(220))
        self.lyric_holder = BoxLayout(orientation="vertical", size_hint_y=None,
                                      spacing=dp(2), padding=(dp(6), 0))
        self.lyric_holder.bind(minimum_height=self.lyric_holder.setter("height"))
        self.lyric_scroll.add_widget(self.lyric_holder)
        lyric_card.add_widget(self.lyric_scroll)
        self.box.add_widget(lyric_card)

    def _on_volume(self, *a):
        v = int(self.sld_vol.value)
        self.lbl_vol.text = f"{v}%"
        self.app.cmd("volume", value=v / 100.0)

    def set_lyric_lines(self, lines, times):
        self.lyric_holder.clear_widgets()
        self._lyric_lines = lines or []
        self._lyric_times = times or []
        for i, ln in enumerate(self._lyric_lines):
            self.lyric_holder.add_widget(Lbl(text=ln, color=MUTED, font_size=sp(11.5),
                                            halign="left", size_hint_y=None,
                                            height=dp(20)))


class SettingsScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="settings", **kw)
        card = Card()
        card.add_widget(Lbl(text="재생 설정", color=FG, bold=True, font_size=sp(12.5),
                            halign="left", valign="middle", text_size=(None, None)))

        def row(title, key, values=None):
            r = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40),
                          spacing=dp(8))
            r.add_widget(Lbl(text=title, color=FG, font_size=sp(12), halign="left"))
            if values is None:
                sw = Switch(active=bool(self.app.settings.get(key)))
                sw.bind(active=lambda inst, val: self.app.set_setting(key, val))
                r.add_widget(sw)
            else:
                sp = Spinner(text=str(self.app.settings.get(key)),
                             values=values, size_hint_x=None, width=dp(110),
                             font_size=sp(11.5), background_normal="",
                             background_down="", background_color=FIELD, color=FG)
                sp.bind(text=lambda inst, val: self.app.set_setting(key, val))
                r.add_widget(sp)
            card.add_widget(r)

        row("무한 재생", "infinite")
        row("셔플", "shuffle")
        row("반복", "repeat", ["all", "one", "off"])
        self.box.add_widget(card)

        info = Card()
        info.add_widget(Lbl(text="정보", color=FG, bold=True, font_size=sp(12.5),
                            halign="left", valign="middle", text_size=(None, None)))
        self.lbl_info = Lbl(text="", color=MUTED, font_size=sp(11), halign="left")
        info.add_widget(self.lbl_info)
        self.box.add_widget(info)

    def refresh_info(self):
        try:
            cache = config.CACHE_DIR
            size = sum(f.stat().st_size for f in cache.glob("*") if f.is_file())
            n = len(list(cache.glob("*")))
            self.lbl_info.text = (f"앱 버전 {config.VERSION}\n"
                                  f"캐시 파일 {n}개 / {size/1048576:.1f} MB\n"
                                  f"데이터 폴더\n{config.DATA_DIR}")
        except Exception:
            self.lbl_info.text = ""


# ---------------------------------------------------------------------------
# 앱
# ---------------------------------------------------------------------------
class MusicApp(App):
    title = "무한 음악 플레이어"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.settings = config.load_settings()
        self.client = ServiceClient()
        self.downloader = Downloader()
        self.tracks: list = []
        self._lyric_lines: list = []
        self._lyric_times: list = []
        self._last_track_key = ""
        self._seeking = False

    # ---------------------------------------------------------- 빌드
    def build(self):
        self.root_box = BoxLayout(orientation="vertical")
        head = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(46),
                         padding=(dp(10), 0), spacing=dp(6))
        with head.canvas.before:
            Color(*HEADER)
            head_bg = Rectangle(pos=head.pos, size=head.size)
        head.bind(pos=lambda *a: setattr(head_bg, "pos", head.pos),
                  size=lambda *a: setattr(head_bg, "size", head.size))
        head.add_widget(Lbl(text="무한 음악 플레이어", color=FG, bold=True,
                            font_size=sp(14), halign="left", valign="middle",
                            text_size=(None, None)))
        self.head_info = Lbl(text="", color=MUTED, font_size=sp(10), halign="right",
                             valign="middle", text_size=(None, None))
        head.add_widget(self.head_info)
        self.root_box.add_widget(head)

        self.sm = ScreenManager(transition=NoTransition())
        self.chart_screen = ChartScreen(self)
        self.player_screen = PlayerScreen(self)
        self.settings_screen = SettingsScreen(self)
        for s in (self.chart_screen, self.player_screen, self.settings_screen):
            self.sm.add_widget(s)
        self.root_box.add_widget(self.sm)

        nav = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(54))
        with nav.canvas.before:
            Color(*NAV)
            nav_bg = Rectangle(pos=nav.pos, size=nav.size)
        nav.bind(pos=lambda *a: setattr(nav_bg, "pos", nav.pos),
                 size=lambda *a: setattr(nav_bg, "size", nav.size))
        for name, label in (("chart", "차트"), ("player", "재생"), ("settings", "설정")):
            b = FlatButton(text=label, bg=NAV, height=dp(54))
            b.bind(on_release=lambda *a, n=name: self.goto(n))
            nav.add_widget(b)
        self.root_box.add_widget(nav)

        self.goto("chart")
        Clock.schedule_interval(self.poll_state, 0.4)
        return self.root_box

    def goto(self, name):
        self.sm.current = name
        if name == "settings":
            self.settings_screen.refresh_info()

    # ---------------------------------------------------------- 차트
    def load_chart(self):
        src = self.chart_screen.selected_source()
        self.chart_screen.set_tracks([])
        self.head_info.text = "불러오는 중..."

        def work():
            try:
                if src.kind == "melon":
                    tracks = chart_mod.fetch_melon_songs(src.url, limit=self.settings.get("chart_limit", 50))
                elif src.kind == "genie":
                    tracks = chart_mod.fetch_genie_chart(src.url, limit=self.settings.get("chart_limit", 50))
                else:
                    tracks = self.downloader.search(src.query, limit=self.settings.get("chart_limit", 50))
            except Exception as exc:
                Clock.schedule_once(lambda *a: self._chart_failed(str(exc)), 0)
                return
            Clock.schedule_once(lambda *a: self._chart_loaded(tracks), 0)

        threading.Thread(target=work, daemon=True).start()

    def _chart_loaded(self, tracks):
        self.tracks = tracks
        self.chart_screen.set_tracks(tracks)
        self.head_info.text = f"{len(tracks)}곡"
        # 서비스에 재생목록 전달
        self.client.send("playlist", tracks=[t.to_dict() for t in self.tracks])

    def _chart_failed(self, msg):
        self.head_info.text = "불러오기 실패"
        self.chart_screen.set_tracks([])
        self._set_status(msg)

    # ---------------------------------------------------------- 재생
    def play_track(self, track):
        for i, t in enumerate(self.tracks):
            if t.key == track.key:
                self.client.send("play", index=i)
                self.goto("player")
                self._load_lyrics(track)
                return
        # 목록에 없으면(단일 곡) 그대로 재생
        self.client.send("playlist", tracks=[track.to_dict()])
        self.client.send("play", index=0)
        self.goto("player")
        self._load_lyrics(track)

    def cmd(self, name, **payload):
        self.client.send(name, **payload)

    def set_setting(self, key, value):
        self.settings[key] = value
        config.save_settings(self.settings)
        if key in ("repeat", "shuffle", "infinite"):
            self.cmd(key, value=value)

    def _set_status(self, msg):
        self.player_screen.lbl_status.text = msg

    # ---------------------------------------------------------- 가사
    def _load_lyrics(self, track):
        if not self.settings.get("lyrics_enabled", True):
            return
        if track.key == self._last_track_key:
            return
        self._last_track_key = track.key
        self.player_screen.lbl_lyric.text = "가사 가져오는 중..."

        def work():
            try:
                text, source = lyrics_mod.fetch_lyrics(track)
            except Exception:
                text, source = "", ""
            lines = lyrics_mod.split_lines(text)
            times = []
            try:
                if track.video_id:
                    caps = lyrics_mod.fetch_youtube_captions(track.video_id)
                    if caps:
                        times = lyrics_mod.align_with_captions(lines, caps, track.duration)
            except Exception:
                times = []
            if not times and lines:
                times = lyrics_mod.build_timeline(lines, track.duration or 180.0)
            Clock.schedule_once(lambda *a: self._lyrics_ready(lines, times, source), 0)

        threading.Thread(target=work, daemon=True).start()

    def _lyrics_ready(self, lines, times, source):
        self._lyric_lines = lines
        self._lyric_times = times
        self.player_screen.set_lyric_lines(lines, times)
        if not lines:
            self.player_screen.lbl_lyric.text = "가사를 찾지 못했습니다"

    # ---------------------------------------------------------- 상태 폴링
    def poll_state(self, dt):
        st = self.client.state()
        if not st:
            return
        title = st.get("title") or ""
        artist = st.get("artist") or ""
        self.player_screen.lbl_title.text = title or "재생할 곡이 없습니다"
        self.player_screen.lbl_artist.text = artist
        self.player_screen.lbl_status.text = st.get("error") or st.get("status") or ""
        dur = float(st.get("dur") or 0.0)
        pos = float(st.get("pos") or 0.0)
        if not self._seeking:
            self.player_screen.sld_pos.value = (pos / dur * 100.0) if dur > 0 else 0
        self.player_screen.lbl_time.text = f"{int(pos//60)}:{int(pos%60):02d} / {int(dur//60)}:{int(dur%60):02d}"
        self.player_screen.b_play.text = "⏸" if st.get("playing") else "▶"
        # 가사 하이라이트
        if self._lyric_lines and self._lyric_times:
            try:
                idx = lyrics_mod.line_index_at(self._lyric_times, pos)
            except Exception:
                idx = 0
            if 0 <= idx < len(self._lyric_lines):
                self.player_screen.lbl_lyric.text = self._lyric_lines[idx]
        # 볼륨 표시
        v = st.get("volume")
        if v is not None and not self._seeking:
            self.player_screen.sld_vol.value = float(v) * 100
            self.player_screen.lbl_vol.text = f"{int(float(v)*100)}%"

    # ---------------------------------------------------------- 시작
    def on_start(self):
        self.client.start("무한 음악 플레이어", "재생 대기 중")
        self.client.send("volume", value=float(self.settings.get("volume", 0.8)))
        self.client.send("repeat", value=self.settings.get("repeat", "all"))
        self.client.send("shuffle", value=bool(self.settings.get("shuffle")))
        self.client.send("infinite", value=bool(self.settings.get("infinite")))
        self.player_screen.sld_vol.value = float(self.settings.get("volume", 0.8)) * 100


if __name__ == "__main__":
    MusicApp().run()
