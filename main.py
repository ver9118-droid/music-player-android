#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""무한 음악 플레이어 — 안드로이드(Kivy) 버전.

데스크톱 버전(music-player)의 소스/가사/검색 로직을 재사용하고,
재생은 안드로이드 별도 프로세스(포그라운드 서비스)에서 Native MediaPlayer 로
수행한다.  덕분에 화면을 나가도/앱을 닫아도 음악이 계속 재생된다.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _crash_log(text):
    """표준 라이브러리만 써서 로그 파일에 남긴다(임포트 실패 시에도 동작)."""
    try:
        with open(os.path.join(_HERE, "app.log"), "a", encoding="utf-8") as fp:
            fp.write(text)
    except Exception:
        pass


def _fatal_excepthook(exc_type, exc, tb):
    """예기치 못한 예외를 로그 파일에도 남긴다."""
    try:
        _crash_log("=== FATAL %s ===\n%s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"),
            "".join(traceback.format_exception(exc_type, exc, tb))))
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _fatal_excepthook

# ── 임포트 단계에서 실패해도 원인을 알 수 있게 감싼다 ──────────
try:
    from mplayer import config  # noqa: E402
    config.ensure_dirs()
    config.setup_tls()
    config.log_line("앱 시작 (main.py import)")
except Exception:                                   # pragma: no cover
    _crash_log("=== import(mplayer.config) 실패 ===\n%s\n"
               % traceback.format_exc())
    raise

try:
    from kivy.app import App                                  # noqa: E402
    from kivy.clock import Clock                              # noqa: E402
    from kivy.core.text import LabelBase, DEFAULT_FONT        # noqa: E402
    from kivy.graphics import Color, RoundedRectangle, Rectangle  # noqa: E402
    from kivy.metrics import dp, sp                           # noqa: E402
    from kivy.properties import ListProperty, NumericProperty  # noqa: E402
    from kivy.uix.behaviors import ButtonBehavior             # noqa: E402
    from kivy.uix.boxlayout import BoxLayout                  # noqa: E402
    from kivy.uix.button import Button                        # noqa: E402
    from kivy.uix.image import Image as KvImage               # noqa: E402
    from kivy.uix.label import Label as _KivyLabel            # noqa: E402
    from kivy.uix.scrollview import ScrollView                # noqa: E402
    from kivy.uix.screenmanager import (ScreenManager, Screen,  # noqa: E402
                                         NoTransition)
    from kivy.uix.spinner import Spinner                      # noqa: E402
    from kivy.uix.slider import Slider                        # noqa: E402
    from kivy.uix.switch import Switch                        # noqa: E402
    from kivy.uix.textinput import TextInput                  # noqa: E402
except Exception:                                   # pragma: no cover
    _crash_log("=== import(kivy) 실패 ===\n%s\n" % traceback.format_exc())
    raise

try:
    from mplayer import chart as chart_mod                    # noqa: E402
    from mplayer.downloader import Downloader, ytdlp_status   # noqa: E402
    from mplayer.favorites import Favorites                   # noqa: E402
    from mplayer.models import Track                          # noqa: E402
    from mplayer.service_client import ServiceClient          # noqa: E402
    from mplayer.sources import FAVORITE_PREFIX, SOURCES      # noqa: E402
except Exception:                                   # pragma: no cover
    _crash_log("=== import(mplayer.*) 실패 ===\n%s\n" % traceback.format_exc())
    raise



# ---------------------------------------------------------------------------
# 폰트 (한글 렌더링에 필요)
# ---------------------------------------------------------------------------
FONT_R = os.path.join(_HERE, "assets", "NanumGothic-Regular.ttf")
FONT_B = os.path.join(_HERE, "assets", "NanumGothic-Bold.ttf")
if os.path.exists(FONT_R):
    # 굵은 글꼴이 없으면 같은 파일로 등록한다.
    # SDL2_ttf 가 자동으로 "가상 굵게(faux bold)" 로 처리해 준다.
    # (NanumGothic-Bold.ttf 는 2MB 라 APK 용량 축소 대상에서 제외했다)
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
HIST_SEL = C("#2a3f63")
HIST_NOW = C("#4a2436")
GREEN = C("#2f9e5f")
RED = C("#e74c3c")
ORANGE = C("#f39c12")


# ---------------------------------------------------------------------------
# 공통 위젯
# ---------------------------------------------------------------------------
def labels_rev(labels: dict, shown: str) -> str:
    """표시 문자열 → 실제 저장 값 (없으면 그대로)."""
    for key, val in (labels or {}).items():
        if val == shown:
            return key
    return shown


class ListScrollView(ScrollView):
    """목록용 스크롤뷰.

    Kivy 의 ScrollView 는 기본적으로 250ms 동안 "스크롤인가 탭인가" 를
    판단하지 않는다.  그 동안 자식(버튼/목록행) 은 터치를 받지 못하기
    때문에 "눌렀는데 아무 반응이 없다" 처럼 느껴진다.
    → 판정 시간을 짧게 하고, 빠르게 뗀 터치도 목록행이 처리할 수 있도록
      터치 시작 위치를 기억해 둔다.
    """

    scroll_timeout = NumericProperty(60)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._touch_start = {}

    def on_touch_down(self, touch):
        try:
            touch.push()
            touch.apply_transform_2d(self.to_local)
            self._touch_start[touch] = (touch.x, touch.y)
            touch.pop()
        except Exception:
            pass
        return super().on_touch_down(touch)

    def touch_started_at(self, touch):
        """터치가 시작된 좌표(콘텐츠 공간). 없으면 None."""
        return self._touch_start.get(touch)

    def on_touch_up(self, touch):
        self._touch_start.pop(touch, None)
        return super().on_touch_up(touch)


def find_scroll_view(widget):
    """위젯을 감싸고 있는 ListScrollView 를 찾는다 (없으면 None)."""
    p = getattr(widget, "parent", None)
    while p is not None:
        if isinstance(p, ListScrollView):
            return p
        p = getattr(p, "parent", None)
    return None


class Lbl(_KivyLabel):
    """위젯 크기에 맞춰 text_size 를 잡는 라벨."""
    def __init__(self, **kw):
        kw.pop("text_size", None)
        # 높이는 라벨이 스스로 잡게 한다 (Card 안에서 최소높이가 0 이 되는 문제 방지)
        kw.setdefault("size_hint_y", None)
        super().__init__(**kw)
        self.bind(size=self._fit)
        self._fit()

    def _fit(self, *a):
        # 높이가 아직 정해지지 않았으면(None) 라벨이 스스로 높이 잡게 한다.
        #  (높이 0 으로 text_size 를 고정하면 텍스처가 0 높이라 영영 안 보인다)
        h = self.height if self.height > 0 else None
        self.text_size = (self.width, h)


def fix_height(box, height):
    """명시적 높이를 가진 컨테이너를 만듭니다.

    Kivy 의 BoxLayout 는 자식의 minimum_height 로 부모 최소높이를 계산한다.
    고정 높이를 준 행은 minimum_height 도 같이 지정해야 카드가 접히지 않는다.
    (minimum_height 를 height 에 바인딩하면 최소높이가 높이를 덮어써 접힌다)
    """
    box.height = height
    box.minimum_height = height
    return box


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
        # 카드 높이는 내용(자식 최소높이 합)을 따라간다
        self.bind(minimum_height=self.setter("height"))
        self._sync()

    def _sync(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size


class FlatButton(Button):
    bg = ListProperty([0.17, 0.21, 0.27, 1])

    def __init__(self, **kw):
        kw.setdefault("background_normal", "")
        kw.setdefault("background_down", "")
        kw.setdefault("background_color", (0, 0, 0, 0))
        kw.setdefault("font_size", sp(13))
        kw.setdefault("color", FG)
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(44))
        # width 를 명시했으면 size_hint_x 를 꺼야 실제로 그 너비가 적용된다.
        if kw.get("width") is not None and "size_hint_x" not in kw:
            kw["size_hint_x"] = None
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
        c = list(self.bg)
        if self.state == "down":
            c = [max(0, v * 0.72) for v in c[:3]] + [c[3]]
        self._c.rgba = c


class IconButton(FlatButton):
    """재생/일시정지 같은 큰 버튼."""

    def __init__(self, **kw):
        kw.setdefault("font_size", sp(18))
        kw.setdefault("height", dp(56))
        kw.setdefault("size_hint_x", None)
        kw.setdefault("width", dp(84))
        super().__init__(**kw)


class TappableRow(ButtonBehavior, BoxLayout):
    """눌릴 수 있는 행.

    ※ Kivy 는 ButtonBehavior 를 mixin 으로 붙인 위젯에서만 on_release 를
    발생시킨다.  (plain BoxLayout 에 on_release 를 bind 하면 절대 호출되지
    않는다 — 이게 "곡을 눌러도 아무 반응이 없는" 원인이었다)
    """

    def __init__(self, **kw):
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("size_hint_y", None)
        kw.setdefault("spacing", dp(8))
        kw.setdefault("padding", (dp(6), 0))
        super().__init__(**kw)
        self._base_bg = HIST
        self._c = Color(*HIST)
        self._r = RoundedRectangle(radius=[dp(8)])
        self.canvas.before.add(self._c)
        self.canvas.before.add(self._r)
        self.bind(pos=self._sync, size=self._sync, state=self._sync)
        self._sync()

    def _sync(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size
        c = list(self._base_bg)
        if self.state == "down":
            c = [max(0.0, v * 0.75) for v in c[:3]] + [c[3]]
        self._c.rgba = c

    def set_bg(self, rgba):
        self._base_bg = rgba
        self._sync()


class TrackRow(TappableRow):
    """차트 목록 한 줄.  왼쪽 영역을 누르면 선택(다중 선택) 토글."""

    SELECT_ZONE = dp(46)

    def __init__(self, app, track, **kw):
        kw.setdefault("height", dp(56))
        super().__init__(**kw)
        self.app = app
        self.track = track
        self.selected = False
        self.now_playing = False
        self._local_x = None
        self._pressed = False
        self._acted = False

        self.lbl_mark = Lbl(text=str(track.rank or "-"), color=MUTED,
                            font_size=sp(12), size_hint_x=None, width=dp(24),
                            halign="center", valign="middle")
        self.add_widget(self.lbl_mark)

        info = BoxLayout(orientation="vertical", spacing=dp(1))
        self.lbl_title = Lbl(text=track.title, color=FG, font_size=sp(12.5),
                             halign="left", valign="bottom",
                             size_hint_y=None, height=dp(24))
        sub = track.artist or track.source
        self.lbl_sub = Lbl(text=sub, color=MUTED, font_size=sp(10),
                           halign="left", valign="top",
                           size_hint_y=None, height=dp(18))
        info.add_widget(self.lbl_title)
        info.add_widget(self.lbl_sub)
        self.add_widget(info)

        self.lbl_tail = Lbl(text="▶", color=ACCENT, font_size=sp(15),
                            size_hint_x=None, width=dp(32), halign="center",
                            valign="middle")
        self.add_widget(self.lbl_tail)

    # ------------------------------------------------------------- 터치 처리
    def on_touch_down(self, touch):
        # 누른 위치를 미리 기억한다
        #  (Kivy 2.3 의 on_release 에는 touch 가 넘어오지 않는다)
        #  touch 좌표는 "부모(=컨테이너) 공간" 이므로 self.x 를 빼야 행 안 위치가 된다.
        try:
            self._local_x = touch.x - self.x
        except Exception:
            self._local_x = None
        self._pressed = False
        self._acted = False
        return super().on_touch_down(touch)

    def on_press(self, *a):
        # Kivy 의 ScrollView 는 on_release 이 "손을 뗀 뒤 0.2초 뒤" 에
        # 발생한다.  재생/선택은 누름(탭 확정) 시점에 처리해야 즉각 반응한다.
        self._pressed = True
        self._act()

    def on_release(self, *a):
        """※ Kivy 2.3 에서는 on_release 에 touch 가 넘어오지 않는다."""
        self._act()

    def on_touch_up(self, touch):
        # 스크롤뷰가 "탭/스크롤" 을 판단하기 전에 빠르게 뗀 경우에도 반응한다.
        if not self._pressed and not self._acted:
            sv = find_scroll_view(self)
            start = sv.touch_started_at(touch) if sv is not None else None
            if start is not None:
                sx, sy = start
                if self.x <= sx <= self.right and self.y <= sy <= self.top:
                    self._local_x = sx - self.x
                    self._act()
        return super().on_touch_up(touch)

    def _act(self):
        if self._acted:
            return
        self._acted = True
        lx = getattr(self, "_local_x", None)
        if lx is not None and lx < self.SELECT_ZONE:
            # 왼쪽(순번) 영역 → 선택 토글
            self.app.toggle_select(self.track)
        else:
            self.app.play_track(self.track)

    # ------------------------------------------------------------- 상태 표시
    def set_selected(self, flag: bool):
        self.selected = flag
        self._refresh()

    def set_now_playing(self, flag: bool):
        self.now_playing = flag
        self._refresh()

    def _refresh(self):
        if self.now_playing:
            self.set_bg(HIST_NOW)
            self.lbl_mark.text = "▶"
            self.lbl_mark.color = ACCENT
            self.lbl_title.color = FG
            self.lbl_title.bold = True
            self.lbl_tail.text = "♪"
        elif self.selected:
            self.set_bg(HIST_SEL)
            self.lbl_mark.text = "✓"
            self.lbl_mark.color = ACCENT
            self.lbl_title.color = FG
            self.lbl_title.bold = False
            self.lbl_tail.text = ""
        else:
            self.set_bg(HIST)
            self.lbl_mark.text = str(self.track.rank or "-")
            self.lbl_mark.color = MUTED
            self.lbl_title.color = FG
            self.lbl_title.bold = False
            self.lbl_tail.text = ""


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
        sv = ListScrollView(do_scroll_x=False, bar_width=dp(3))
        sv.add_widget(self.box)
        root.add_widget(sv)
        self.add_widget(root)

    def section(self, title):
        card = Card()
        card.add_widget(Lbl(text=title, color=FG, bold=True, font_size=sp(12.5),
                            halign="left", valign="middle"))
        self.box.add_widget(card)
        return card


class ChartScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="chart", **kw)

        # ── 소스 선택 + 불러오기
        card = Card()
        row = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                    spacing=dp(6)), dp(42))
        self.sp_source = Spinner(text=app.source_labels()[0],
                                  values=app.source_labels(),
                                  size_hint_y=None, height=dp(40), font_size=sp(12),
                                  background_normal="", background_down="",
                                  background_color=FIELD, color=FG)
        self.sp_source.bind(text=lambda *a: self._on_source_changed())
        btn = FlatButton(text="불러오기", bg=ACCENT, color=PAGE, width=dp(84))
        btn.bind(on_release=lambda *a: self.app.load_chart())
        row.add_widget(self.sp_source)
        row.add_widget(btn)
        card.add_widget(row)
        self.box.add_widget(card)

        # ── 다중 선택 도구
        self.sel_card = Card()
        srow = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                     spacing=dp(6)), dp(42))
        self.lbl_sel = Lbl(text="선택 0곡", color=MUTED, font_size=sp(12),
                           halign="left", valign="middle",
                           size_hint_y=None, height=dp(42))
        b_play = FlatButton(text="선택 재생", bg=GREEN, color=PAGE, width=dp(88))
        b_play.bind(on_release=lambda *a: self.app.play_selected())
        b_fav = FlatButton(text="★ 추가", bg=FIELD, width=dp(80))
        b_fav.bind(on_release=lambda *a: self.app.add_selected_to_favorites())
        b_clear = FlatButton(text="해제", bg=FIELD, width=dp(56))
        b_clear.bind(on_release=lambda *a: self.app.clear_selection())
        b_save = FlatButton(text="💾 저장", bg=FIELD, width=dp(76),
                            font_size=sp(11))
        b_save.bind(on_release=lambda *a: self.app.save_selected())
        srow.add_widget(self.lbl_sel)
        srow.add_widget(b_play)
        srow.add_widget(b_fav)
        srow.add_widget(b_save)
        srow.add_widget(b_clear)
        self.sel_card.add_widget(srow)
        self.box.add_widget(self.sel_card)

        # ── 목록
        self.list_card = Card()
        self.list_holder = BoxLayout(orientation="vertical", size_hint_y=None,
                                      spacing=dp(4))
        self.list_holder.bind(minimum_height=self.list_holder.setter("height"))
        self.list_card.add_widget(self.list_holder)
        self.box.add_widget(self.list_card)

    def _on_source_changed(self, *a):
        self.app.on_source_changed(self.sp_source.text)

    def set_tracks(self, tracks):
        self.list_holder.clear_widgets()
        if not tracks:
            self.list_holder.add_widget(
                Lbl(text="불러오기를 눌러 차트를 가져오세요.",
                   color=MUTED, font_size=sp(12), halign="left"))
            return
        for t in tracks:
            self.list_holder.add_widget(TrackRow(self.app, t))

    def set_selection_info(self, count: int):
        self.lbl_sel.text = f"선택 {count}곡"
        self.lbl_sel.color = ACCENT if count else MUTED


class PlayerScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="player", **kw)
        card = Card()
        art_row = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                       spacing=dp(10)), dp(120))
        self.art = KvImage(size_hint_x=None, width=dp(110), allow_stretch=True,
                           keep_ratio=True, color=(1, 1, 1, 1), opacity=0)
        art_row.add_widget(self.art)
        info = BoxLayout(orientation="vertical", spacing=dp(2))
        self.lbl_title = Lbl(text="재생할 곡이 없습니다", color=FG, bold=True,
                             font_size=sp(14), halign="left", valign="bottom",
                             size_hint_y=None, height=dp(28))
        self.lbl_artist = Lbl(text="", color=MUTED, font_size=sp(11.5),
                              halign="left", valign="middle",
                              size_hint_y=None, height=dp(20))
        self.lbl_status = Lbl(text="", color=ORANGE, font_size=sp(10.5),
                              halign="left", valign="middle",
                              size_hint_y=None, height=dp(18))
        info.add_widget(self.lbl_title)
        info.add_widget(self.lbl_artist)
        info.add_widget(self.lbl_status)
        art_row.add_widget(info)
        card.add_widget(art_row)

        # 진행바
        prog = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                     spacing=dp(6)), dp(24))
        self.sld_pos = Slider(min=0, max=100, value=0, size_hint_x=1,
                              cursor_size=(dp(22), dp(22)))
        self.sld_pos.bind(value=self._on_pos_value)
        self.sld_pos.bind(on_touch_down=self._on_pos_down)
        self.sld_pos.bind(on_touch_up=self._on_pos_release)
        self.lbl_time = Lbl(text="0:00 / 0:00", color=MUTED, font_size=sp(10),
                            size_hint_x=None, width=dp(80), halign="right")
        prog.add_widget(self.sld_pos)
        prog.add_widget(self.lbl_time)
        card.add_widget(prog)

        # 재생 제어
        ctrl = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                     spacing=dp(8)), dp(62))
        b_prev = IconButton(text="이전", bg=FIELD, width=dp(70))
        b_prev.bind(on_release=lambda *a: self.app.cmd("prev"))
        self.b_play = IconButton(text="재생", bg=GREEN, width=dp(96))
        self.b_play.bind(on_release=lambda *a: self.app.cmd("toggle"))
        b_next = IconButton(text="다음", bg=FIELD, width=dp(70))
        b_next.bind(on_release=lambda *a: self.app.cmd("next"))
        ctrl.add_widget(b_prev)
        ctrl.add_widget(self.b_play)
        ctrl.add_widget(b_next)
        card.add_widget(ctrl)

        # 재생 모드 (셔플 / 반복 / 무한)
        modes = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                      spacing=dp(6)), dp(40))
        self.b_shuffle = FlatButton(text="셔플 OFF", bg=FIELD, font_size=sp(12))
        self.b_shuffle.bind(on_release=lambda *a: self.app.toggle_shuffle())
        self.b_repeat = FlatButton(text="반복 전체", bg=FIELD, font_size=sp(12))
        self.b_repeat.bind(on_release=lambda *a: self.app.cycle_repeat())
        self.b_inf = FlatButton(text="무한 ON", bg=FIELD, font_size=sp(12))
        self.b_inf.bind(on_release=lambda *a: self.app.toggle_infinite())
        modes.add_widget(self.b_shuffle)
        modes.add_widget(self.b_repeat)
        modes.add_widget(self.b_inf)
        card.add_widget(modes)

        # 볼륨
        vol = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                    spacing=dp(6)), dp(34))
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

        # 기기 저장 / 종료
        act = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                    spacing=dp(6)), dp(40))
        b_save = FlatButton(text="💾 기기 저장", bg=FIELD, font_size=sp(12),
                            size_hint_x=None, width=dp(130))
        b_save.bind(on_release=lambda *a: self.app.save_current())
        b_quit = FlatButton(text="⏻ 종료(재생까지)", bg=RED, color=(1, 1, 1, 1),
                            font_size=sp(12), size_hint_x=None, width=dp(140))
        b_quit.bind(on_release=lambda *a: self.app.quit_app())
        act.add_widget(b_save)
        act.add_widget(b_quit)
        card.add_widget(act)
        self.box.add_widget(card)

    # ------------------------------------------------------------- 콜백
    def _on_volume(self, *a):
        v = int(self.sld_vol.value)
        self.lbl_vol.text = f"{v}%"
        self.app.cmd("volume", value=v / 100.0)

    def _on_pos_value(self, *a):
        # 슬라이더를 움직이는 동안에는 자동 갱신하지 않는다
        pass

    def _on_pos_down(self, *a):
        self.app._seeking = True

    def _on_pos_release(self, *a):
        self.app._seeking = False
        Clock.schedule_once(lambda *a: self.app.seek_to_ratio(
            self.sld_pos.value / 100.0), 0)


class FavoritesScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="favorites", **kw)

        card = Card()
        card.add_widget(Lbl(text="즐겨찾기", color=FG, bold=True, font_size=sp(12.5),
                            halign="left", valign="middle"))
        row = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                    spacing=dp(6)), dp(42))
        self.txt_name = TextInput(text="내 목록", multiline=False,
                                  size_hint_y=None, height=dp(40),
                                  font_size=sp(13), background_color=FIELD,
                                  foreground_color=FG, cursor_color=ACCENT,
                                  padding=[dp(8), dp(8)])
        b_save = FlatButton(text="현재 목록 저장", bg=ACCENT, color=PAGE, width=dp(104))
        b_save.bind(on_release=lambda *a: self.app.save_favorites(self.txt_name.text))
        row.add_widget(self.txt_name)
        row.add_widget(b_save)
        card.add_widget(row)
        self.box.add_widget(card)

        card2 = Card()
        card2.add_widget(Lbl(text="저장된 목록", color=FG, bold=True,
                             font_size=sp(12.5), halign="left", valign="middle"))
        card2.add_widget(Lbl(text="※ 목록을 누르면 재생목록으로 불러옵니다",
                             color=MUTED, font_size=sp(10), halign="left"))
        self.list_holder = BoxLayout(orientation="vertical", size_hint_y=None,
                                      spacing=dp(4))
        self.list_holder.bind(minimum_height=self.list_holder.setter("height"))
        card2.add_widget(self.list_holder)
        self.box.add_widget(card2)

        card3 = Card()
        r3 = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                   spacing=dp(6)), dp(42))
        b_add = FlatButton(text="선택곡 추가", bg=FIELD, width=dp(100))
        b_add.bind(on_release=lambda *a: self.app.add_selected_to_favorites())
        b_del = FlatButton(text="선택 삭제", bg=FIELD, width=dp(100))
        b_del.bind(on_release=lambda *a: self.app.delete_favorite())
        b_ren = FlatButton(text="이름 변경", bg=FIELD, width=dp(100))
        b_ren.bind(on_release=lambda *a: self.app.rename_favorite(self.txt_name.text))
        r3.add_widget(b_add)
        r3.add_widget(b_del)
        r3.add_widget(b_ren)
        card3.add_widget(r3)
        self.box.add_widget(card3)

        self.selected_id = ""

    def set_lists(self, items):
        self.list_holder.clear_widgets()
        if not items:
            self.list_holder.add_widget(
                Lbl(text="저장된 목록이 없습니다.\n위에서 '현재 목록 저장'을 누르세요.",
                   color=MUTED, font_size=sp(12), halign="left"))
            return
        for it in items:
            row = TappableRow(height=dp(52))
            row.bind(on_release=lambda inst, *a, i=it: self.app.pick_favorite(i))
            title = it.get("name", "")
            count = len(it.get("tracks") or [])
            row.add_widget(Lbl(text="★", color=ACCENT, font_size=sp(13),
                               size_hint_x=None, width=dp(26), halign="center",
                               valign="middle",
                               size_hint_y=None, height=dp(52)))
            info = BoxLayout(orientation="vertical", spacing=dp(1))
            info.add_widget(Lbl(text=title, color=FG, font_size=sp(12.5),
                                halign="left", valign="bottom",
                                size_hint_y=None, height=dp(22)))
            info.add_widget(Lbl(text=f"{count}곡 · {it.get('created','')}",
                                color=MUTED, font_size=sp(10),
                                halign="left", valign="top",
                                size_hint_y=None, height=dp(18)))
            row.add_widget(info)
            row.add_widget(Lbl(text="▶", color=ACCENT, font_size=sp(14),
                               size_hint_x=None, width=dp(28), halign="center",
                               valign="middle",
                               size_hint_y=None, height=dp(52)))
            self.list_holder.add_widget(row)


class SettingsScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="settings", **kw)

        # ── 재생 설정
        card = Card()
        card.add_widget(Lbl(text="재생 설정", color=FG, bold=True, font_size=sp(12.5),
                            halign="left", valign="middle"))

        def sw_row(title, key):
            r = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                      spacing=dp(8)), dp(40))
            r.add_widget(Lbl(text=title, color=FG, font_size=sp(12),
                             halign="left", valign="middle",
                             size_hint_y=None, height=dp(40)))
            sw = Switch(active=bool(self.app.settings.get(key)),
                        size_hint_y=None, height=dp(40))
            sw.bind(active=lambda inst, val: self.app.set_setting(key, val))
            r.add_widget(sw)
            card.add_widget(r)

        def spin_row(title, key, values, labels=None):
            r = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                      spacing=dp(8)), dp(40))
            r.add_widget(Lbl(text=title, color=FG, font_size=sp(12),
                             halign="left", valign="middle",
                             size_hint_y=None, height=dp(40)))
            cur = str(self.app.settings.get(key))
            labels = labels or {}
            shown = [labels.get(v, v) for v in values]
            if cur not in values:
                values = list(values) + [cur]
                shown = [labels.get(v, v) for v in values]
            text = labels.get(cur, cur)
            spin = Spinner(text=text, values=shown, size_hint_x=None,
                           width=dp(140), size_hint_y=None, height=dp(40),
                           font_size=sp(11.5),
                           background_normal="", background_down="",
                           background_color=FIELD, color=FG)
            spin.bind(text=lambda inst, val: self.app.set_setting(
                key, labels_rev(labels, val)))
            r.add_widget(spin)
            card.add_widget(r)

        sw_row("무한 재생", "infinite")
        sw_row("셔플", "shuffle")
        sw_row("알림 표시", "notify")
        spin_row("반복", "repeat", ["all", "one", "off"],
                 {"all": "전체 반복", "one": "한곡 반복", "off": "반복 없음"})
        spin_row("차트 곡 수", "chart_limit", ["20", "30", "50", "100"])
        spin_row("차트 자동 갱신(시간)", "auto_update_hours",
                 ["0", "3", "6", "12", "24"])
        spin_row("미리 받기(곡)", "prefetch", ["0", "1", "3", "5", "10"])
        spin_row("유튜브 클라이언트", "yt_client",
                 ["auto", "tv", "ios", "android", "web"])
        spin_row("오디오 포맷", "audio_format", ["auto", "m4a", "webm", "mp3"])
        self.box.add_widget(card)

        # ── 검색어
        card2 = Card()
        card2.add_widget(Lbl(text="유튜브 검색어", color=FG, bold=True,
                             font_size=sp(12.5), halign="left", valign="middle"))
        row = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                    spacing=dp(6)), dp(42))
        self.txt_search = TextInput(text=str(self.app.settings.get("search_query")),
                                    multiline=False, size_hint_y=None,
                                    height=dp(40), font_size=sp(12),
                                    background_color=FIELD, foreground_color=FG,
                                    cursor_color=ACCENT, padding=[dp(8), dp(8)])
        b_save = FlatButton(text="저장", bg=ACCENT, color=PAGE, width=dp(64))
        b_save.bind(on_release=lambda *a: self.app.set_setting(
            "search_query", self.txt_search.text))
        row.add_widget(self.txt_search)
        row.add_widget(b_save)
        card2.add_widget(row)
        card2.add_widget(Lbl(text="사용 가능: {artist} {title} {album}\n"
                                "예) {title} {artist} official",
                            color=MUTED, font_size=sp(10.5), halign="left",
                            size_hint_y=None, height=dp(40)))
        self.box.add_widget(card2)

        # ── 정보 / 진단
        info = Card()
        info.add_widget(Lbl(text="정보 · 진단", color=FG, bold=True,
                            font_size=sp(12.5), halign="left", valign="middle"))
        self.lbl_info = Lbl(text="", color=MUTED, font_size=sp(11), halign="left",
                            size_hint_y=None, height=dp(110))
        info.add_widget(self.lbl_info)
        r = fix_height(BoxLayout(orientation="horizontal", size_hint_y=None,
                                  spacing=dp(6)), dp(42))
        b_restart = FlatButton(text="서비스 재시작", bg=FIELD, width=dp(110))
        b_restart.bind(on_release=lambda *a: self.app.restart_service())
        b_log = FlatButton(text="로그 보기", bg=FIELD, width=dp(96))
        b_log.bind(on_release=lambda *a: self.app.show_log())
        r.add_widget(b_restart)
        r.add_widget(b_log)
        info.add_widget(r)
        self.box.add_widget(info)

        self.lbl_log = Lbl(text="", color=MUTED, font_size=sp(9.5), halign="left",
                           size_hint_y=None, height=dp(120))
        log_card = Card()
        log_card.add_widget(self.lbl_log)
        self.box.add_widget(log_card)

    def refresh_info(self):
        try:
            cache = config.CACHE_DIR
            size = sum(f.stat().st_size for f in cache.glob("*") if f.is_file())
            n = len(list(cache.glob("*")))
            ok, ver = ytdlp_status()
            st = self.app.client.state()
            svc = "실행 중" if st.get("alive") else "대기"
            self.lbl_info.text = (
                f"앱 버전 {config.VERSION}\n"
                f"재생 서비스: {svc}"
                f"{'  · 오류: ' + str(st.get('error')) if st.get('error') else ''}\n"
                f"yt-dlp: {ver if ok else '사용 불가 — ' + ver}\n"
                f"캐시 파일 {n}개 / {size/1048576:.1f} MB\n"
                f"데이터 폴더\n{config.DATA_DIR}")
        except Exception:
            self.lbl_info.text = ""

    def set_log(self, text):
        self.lbl_log.text = text


# ---------------------------------------------------------------------------
# 앱
# ---------------------------------------------------------------------------
class MusicApp(App):
    title = "무한 음악 플레이어"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.settings = config.load_settings()
        self.client = ServiceClient()
        self.downloader = Downloader(self.settings)
        self.favorites = Favorites()
        self.tracks: list = []
        self.selection: dict = {}          # key -> Track
        self._last_track_key = ""
        self._seeking = False
        self._now_playing_key = ""
        self._favorite_ids: dict = {}      # "★ 이름" -> list id
        self._pending_fav = ""
        self._auto_timer = None
        self._last_auto = 0.0

    # ---------------------------------------------------------- 빌드
    def build(self):
        try:
            return self._build_ui()
        except Exception:
            tb = traceback.format_exc()
            config.log_line("UI 빌드 오류:\n" + tb)
            return self._error_screen(tb)

    def _error_screen(self, tb):
        """오류가 나도 앱이 죽지 않고 원인을 화면에 보여준다."""
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(6))
        root.add_widget(Lbl(text="앱을 시작하는 중 오류가 발생했습니다.",
                            color=RED, bold=True, font_size=sp(14),
                            halign="left", valign="middle",
                            size_hint_y=None, height=dp(40)))
        detail = (tb or "")[-2500:]
        root.add_widget(Lbl(text=detail, color=MUTED, font_size=sp(9),
                            halign="left", size_hint_y=None, height=dp(420)))
        root.add_widget(Lbl(text="자세한 내용은 앱 폴더의 app.log 에 있습니다.",
                            color=MUTED, font_size=sp(10), halign="left",
                            size_hint_y=None, height=dp(24)))
        return root

    def _build_ui(self):
        config.log_line("UI 빌드 시작")
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
                            size_hint_y=None, height=dp(46)))
        self.head_info = Lbl(text="", color=MUTED, font_size=sp(10), halign="right",
                             valign="middle", size_hint_y=None, height=dp(46))
        head.add_widget(self.head_info)
        self.b_quit = FlatButton(text="⏻ 종료", bg=RED, color=(1, 1, 1, 1),
                                 font_size=sp(11), size_hint_x=None, width=dp(76),
                                 size_hint_y=None, height=dp(32))
        self.b_quit.bind(on_release=lambda *a: self.quit_app())
        head.add_widget(self.b_quit)
        self.root_box.add_widget(head)

        self.sm = ScreenManager(transition=NoTransition())
        self.chart_screen = ChartScreen(self)
        self.player_screen = PlayerScreen(self)
        self.fav_screen = FavoritesScreen(self)
        self.settings_screen = SettingsScreen(self)
        for s in (self.chart_screen, self.player_screen,
                  self.fav_screen, self.settings_screen):
            self.sm.add_widget(s)
        self.root_box.add_widget(self.sm)

        nav = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(54))
        with nav.canvas.before:
            Color(*NAV)
            nav_bg = Rectangle(pos=nav.pos, size=nav.size)
        nav.bind(pos=lambda *a: setattr(nav_bg, "pos", nav.pos),
                 size=lambda *a: setattr(nav_bg, "size", nav.size))
        for name, label in (("chart", "차트"), ("player", "재생"),
                            ("favorites", "★즐겨찾기"), ("settings", "설정")):
            b = FlatButton(text=label, bg=NAV, height=dp(54), font_size=sp(12.5))
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
        elif name == "favorites":
            self.refresh_favorites()

    # ---------------------------------------------------------- 소스 목록
    def source_labels(self):
        labels = [s.display for s in SOURCES]
        for item in self.favorites.lists():
            labels.append(FAVORITE_PREFIX + str(item.get("name", "")))
        return labels

    def refresh_sources(self):
        self._updating_sources = True
        try:
            labels = self.source_labels()
            cur = self.chart_screen.sp_source.text
            self.chart_screen.sp_source.values = labels
            if cur not in labels:
                self.chart_screen.sp_source.text = labels[0]
        except Exception:
            pass
        finally:
            self._updating_sources = False
        self._favorite_ids = {}
        for item in self.favorites.lists():
            self._favorite_ids[FAVORITE_PREFIX + str(item.get("name", ""))] = item.get("id")

    def on_source_changed(self, label):
        """소스 스피너 선택 → 바로 불러오기(즐겨찾기면 재생목록 복원)."""
        if getattr(self, "_updating_sources", False):
            return
        self.refresh_sources()
        if label.startswith(FAVORITE_PREFIX):
            fid = self._favorite_ids.get(label)
            item = self.favorites.get(fid) if fid else None
            if item:
                tracks = [Track.from_dict(t) for t in (item.get("tracks") or [])]
                self._chart_loaded(tracks, label)
            return
        self.load_chart()

    # ---------------------------------------------------------- 차트
    def load_chart(self):
        src = self._selected_source()
        if src is None:
            return
        self.chart_screen.set_tracks([])
        self.head_info.text = "불러오는 중..."

        def work():
            try:
                limit = int(self.settings.get("chart_limit", 50))
                if src.kind == "melon":
                    tracks = chart_mod.fetch_melon_songs(src.url, limit=limit)
                elif src.kind == "genie":
                    tracks = chart_mod.fetch_genie_chart(src.url, limit=limit)
                else:
                    tracks = self.downloader.search(src.query, limit=limit)
            except Exception as exc:
                Clock.schedule_once(lambda *a: self._chart_failed(str(exc)), 0)
                return
            Clock.schedule_once(lambda *a: self._chart_loaded(tracks), 0)

        threading.Thread(target=work, daemon=True).start()

    def _selected_source(self):
        label = self.chart_screen.sp_source.text
        for s in SOURCES:
            if s.display == label:
                return s
        return None

    def _chart_loaded(self, tracks, label=None):
        self.tracks = tracks
        self.chart_screen.set_tracks(tracks)
        self.head_info.text = f"{len(tracks)}곡"
        self._last_auto = time.time()
        # 서비스에 재생목록 전달
        self.client.send("playlist", tracks=[t.to_dict() for t in self.tracks])
        # 상위 N곡은 서비스(다운로드 담당)에서 미리 받는다.
        # (UI 프로세스에서 받으면 같은 파일을 동시에 받아 파일이 깨질 수 있다)
        try:
            count = int(self.settings.get("prefetch", 3))
        except Exception:
            count = 3
        if count > 0 and tracks:
            self.client.send("prefetch", count=count)

    def _chart_failed(self, msg):
        self.head_info.text = "불러오기 실패"
        self.chart_screen.set_tracks([])
        self._set_status(msg)

    # ---------------------------------------------------------- 선택 (다중 선택)
    def toggle_select(self, track):
        if track.key in self.selection:
            self.selection.pop(track.key, None)
        else:
            self.selection[track.key] = track
        self._refresh_rows()
        self.chart_screen.set_selection_info(len(self.selection))

    def clear_selection(self):
        self.selection.clear()
        self._refresh_rows()
        self.chart_screen.set_selection_info(0)

    def _refresh_rows(self):
        holder = self.chart_screen.list_holder
        for child in holder.children:
            if isinstance(child, TrackRow):
                child.set_selected(child.track.key in self.selection)

    def play_selected(self):
        if not self.selection:
            self._set_status("선택된 곡이 없습니다.")
            return
        picked = [t for t in self.tracks if t.key in self.selection]
        if not picked:
            picked = list(self.selection.values())
        self.tracks = picked
        self.chart_screen.set_tracks(picked)
        self.client.send("playlist", tracks=[t.to_dict() for t in picked])
        self.client.send("play", index=0)
        self.goto("player")
        self._load_cover(picked[0])

    # ---------------------------------------------------------- 즐겨찾기
    def refresh_favorites(self):
        self.fav_screen.set_lists(self.favorites.lists())

    def save_favorites(self, name):
        name = (name or "").strip() or "내 즐겨찾기"
        if not self.tracks:
            self._set_status("저장할 재생목록이 없습니다.")
            return
        self.favorites.create(name, self.tracks)
        self.refresh_sources()
        self.refresh_favorites()
        self._set_status(f"'{name}' 목록을 저장했습니다.")

    def add_selected_to_favorites(self):
        tracks = [t for t in self.tracks if t.key in self.selection]
        if not tracks:
            tracks = list(self.selection.values())
        if not tracks:
            self._set_status("추가할 곡이 선택되지 않았습니다.")
            return
        default = self.favorites.default_list()
        self.favorites.add_tracks(default.get("id"), tracks)
        self.refresh_sources()
        self.refresh_favorites()
        self._set_status(f"즐겨찾기에 {len(tracks)}곡을 추가했습니다.")

    def pick_favorite(self, item):
        self.fav_screen.selected_id = item.get("id", "")
        tracks = [Track.from_dict(t) for t in (item.get("tracks") or [])]
        if not tracks:
            self._set_status("빈 목록입니다.")
            return
        self.tracks = tracks
        self.chart_screen.set_tracks(tracks)
        self.client.send("playlist", tracks=[t.to_dict() for t in tracks])
        self.client.send("play", index=0)
        self.goto("player")
        self._load_cover(tracks[0])

    def delete_favorite(self):
        fid = self.fav_screen.selected_id
        if not fid:
            self._set_status("삭제할 목록을 먼저 누르세요.")
            return
        self.favorites.delete(fid)
        self.fav_screen.selected_id = ""
        self.refresh_sources()
        self.refresh_favorites()

    def rename_favorite(self, name):
        fid = self.fav_screen.selected_id
        if not fid:
            self._set_status("이름을 바꿀 목록을 먼저 누르세요.")
            return
        name = (name or "").strip()
        if not name:
            self._set_status("새 이름을 입력하세요.")
            return
        self.favorites.rename(fid, name)
        self.refresh_sources()
        self.refresh_favorites()

    # ---------------------------------------------------------- 재생
    def _load_cover(self, track):
        """표지를 내려받아 앨범아트에 표시한다."""
        def work():
            path = self.downloader.download_thumb(track)
            if not path:
                return
            Clock.schedule_once(lambda *a: self._cover_ready(path), 0)

        threading.Thread(target=work, daemon=True).start()

    def _cover_ready(self, path):
        try:
            self.player_screen.art.source = path
            self.player_screen.art.opacity = 1
            self.player_screen.art.texture_update()
        except Exception:
            pass

    def play_track(self, track):
        # ★ 지금 재생 중인 곡을 다시 누르면 처음부터 다시 재생되지 않도록 한다.
        #   (앱 화면 아무 곳이나 눌렀을 때 곡이 처음으로 돌아가는 문제)
        st = self.client.state() or {}
        cur_key = st.get("key") or ""
        cur_title = (st.get("title") or "").strip()
        same = bool(cur_key) and cur_key == track.key
        if not same and cur_title and cur_title == (track.title or "").strip():
            same = True

        for i, t in enumerate(self.tracks):
            if t.key == track.key:
                if same:
                    # 같은 곡: 재생/일시정지 토글 (위치 유지)
                    self.cmd("toggle")
                    self.goto("player")
                    return
                self.client.send("play", index=i)
                self.goto("player")
                self._load_cover(track)
                return
        # 목록에 없으면(단일 곡) 그대로 재생
        self.client.send("playlist", tracks=[track.to_dict()])
        self.client.send("play", index=0)
        self.goto("player")
        self._load_cover(track)

    def cmd(self, name, **payload):
        self.client.send(name, **payload)

    def seek_to_ratio(self, ratio):
        st = self.client.state()
        dur = float(st.get("dur") or 0.0)
        if dur <= 0:
            return
        self.client.send("seek", pos=max(0.0, min(dur, ratio * dur)))

    def toggle_shuffle(self):
        val = not bool(self.settings.get("shuffle"))
        self.set_setting("shuffle", val)

    def cycle_repeat(self):
        order = ["all", "one", "off"]
        cur = str(self.settings.get("repeat", "all"))
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "all"
        self.set_setting("repeat", nxt)

    def toggle_infinite(self):
        self.set_setting("infinite", not bool(self.settings.get("infinite")))

    def set_setting(self, key, value):
        self.settings[key] = value
        config.save_settings(self.settings)
        if key in ("repeat", "shuffle", "infinite"):
            self.cmd(key, value=value)
        self._refresh_mode_buttons()

    def _refresh_mode_buttons(self):
        ps = self.player_screen
        try:
            ps.b_shuffle.text = "셔플 ON" if self.settings.get("shuffle") else "셔플 OFF"
            ps.b_shuffle.bg = ACCENT if self.settings.get("shuffle") else FIELD
            r = str(self.settings.get("repeat", "all"))
            ps.b_repeat.text = {"all": "반복 전체", "one": "반복 한곡",
                                "off": "반복 꺼짐"}.get(r, "반복 전체")
            ps.b_repeat.bg = ACCENT if r != "off" else FIELD
            inf = bool(self.settings.get("infinite"))
            ps.b_inf.text = "무한 ON" if inf else "무한 OFF"
            ps.b_inf.bg = ACCENT if inf else FIELD
        except Exception:
            pass

    def _set_status(self, msg):
        self.player_screen.lbl_status.text = msg

    # ---------------------------------------------------------- 상태 폴링
    def poll_state(self, dt):
        st = self.client.state()
        if not st:
            return
        title = st.get("title") or ""
        artist = st.get("artist") or ""
        self.player_screen.lbl_title.text = title or "재생할 곡이 없습니다"
        self.player_screen.lbl_artist.text = artist
        status = st.get("error") or st.get("status") or ""
        progress = st.get("progress") or 0
        if st.get("prefetching"):
            status = "다음 곡 미리 받는 중..."
        self.player_screen.lbl_status.text = status
        dur = float(st.get("dur") or 0.0)
        pos = float(st.get("pos") or 0.0)
        if not self._seeking:
            self.player_screen.sld_pos.value = (pos / dur * 100.0) if dur > 0 else 0
        self.player_screen.lbl_time.text = (f"{int(pos//60)}:{int(pos%60):02d} / "
                                            f"{int(dur//60)}:{int(dur%60):02d}")
        self.player_screen.b_play.text = "일시정지" if st.get("playing") else "재생"

        # 재생중 표시
        cur_key = title
        if cur_key != self._now_playing_key:
            self._now_playing_key = cur_key
            # 곡이 바뀌면 진행바는 0 부로 (이전 곡 위치가 넘어오지 않도록)
            self.player_screen.sld_pos.value = 0
            self._refresh_now_playing()

        # 볼륨 표시
        v = st.get("volume")
        if v is not None and not self._seeking:
            self.player_screen.sld_vol.value = float(v) * 100
            self.player_screen.lbl_vol.text = f"{int(float(v)*100)}%"

        self._auto_refresh()

    def _refresh_now_playing(self):
        holder = self.chart_screen.list_holder
        for child in holder.children:
            if isinstance(child, TrackRow):
                child.set_now_playing(child.track.title == self._now_playing_key)

    # ---------------------------------------------------------- 자동 갱신
    def _auto_refresh(self):
        try:
            hours = float(self.settings.get("auto_update_hours", 6))
        except Exception:
            return
        if hours <= 0:
            return
        if time.time() - self._last_auto < hours * 3600:
            return
        self._last_auto = time.time()
        self.load_chart()

    # ---------------------------------------------------------- 기기 저장
    def save_current(self):
        """현재 재생 중인 곡을 기기 공용 저장소로 저장한다.

        ★ 저장 처리는 UI(Activity) 프로세스에서 수행한다.
          서비스 프로세스에는 Activity 가 없어 jnius 의 기본 클래스로더를 쓸 수
          없어 android.os.Build 같은 프레임워크 클래스를 찾지 못하고
          (클래스명 문자열이 반환됨) 저장이 실패했다.
        """
        st = self.client.state() or {}
        path = st.get("file") or ""
        title = (st.get("title") or "").strip()
        artist = (st.get("artist") or "").strip()
        if not path or not os.path.isfile(path):
            self._set_status("저장할 오디오 파일이 아직 준비되지 않았습니다.")
            return
        name = f"{artist} - {title}" if artist else (title or "audio")
        self._set_status("기기에 저장하는 중...")

        def work():
            try:
                from mplayer.exporter import save_to_device
                saved = save_to_device(path, name)
            except Exception as exc:
                Clock.schedule_once(
                    lambda *a: self._set_status(f"저장 실패: {exc}"), 0)
                return
            Clock.schedule_once(
                lambda *a: self._set_status(f"저장 완료: {saved}"), 0)

        threading.Thread(target=work, daemon=True).start()

    def save_selected(self):
        """선택한 곡들을 기기 공용 저장소로 저장한다."""
        picked = [(i, t) for i, t in enumerate(self.tracks)
                  if t.key in self.selection]
        if not picked:
            self._set_status("저장할 곡이 선택되지 않았습니다.")
            return
        for i, _t in picked:
            self.cmd("export", index=i)
        self._set_status(f"{len(picked)}곡을 기기에 저장합니다...")

    # ---------------------------------------------------------- 종료
    def quit_app(self):
        """애플 종료 (재생 서비스까지 정리).

        오 터치 방지를 위해 두 번 눌러야 실제로 종료된다.
        """
        now = time.time()
        if now - getattr(self, "_quit_armed", 0.0) > 3.0:
            self._quit_armed = now
            try:
                self.b_quit.text = "실제 종료?"
            except Exception:
                pass
            Clock.schedule_once(self._quit_cancel, 3.0)
            return
        self._do_quit()

    def _quit_cancel(self, *a):
        self._quit_armed = 0.0
        try:
            self.b_quit.text = "⏻ 종료"
        except Exception:
            pass

    def _do_quit(self):
        self._set_status("종료 중...")
        try:
            self.client.stop()          # 포그라운드 서비스 정지(재생도 멈춤)
        except Exception:
            pass
        Clock.schedule_once(lambda *a: self._finish_quit(), 0.5)

    def _finish_quit(self):
        try:
            from jnius import autoclass
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            if act is not None:
                act.finish()
        except Exception:
            pass
        try:
            self.stop()
        except Exception:
            pass

    # ---------------------------------------------------------- 진단
    def restart_service(self):
        """재생 서비스를 완전히 끄고 다시 띄운다."""
        self.client.stop()
        self._set_status("재생 서비스를 다시 시작합니다...")
        self.head_info.text = "서비스 재시작 중"

        def again():
            ok = self.client.start("무한 음악 플레이어", "재생 대기 중")
            if ok:
                self.client.send("volume",
                                 value=float(self.settings.get("volume", 0.8)))
                self.client.send("repeat", value=self.settings.get("repeat", "all"))
                self.client.send("shuffle", value=bool(self.settings.get("shuffle")))
                self.client.send("infinite", value=bool(self.settings.get("infinite")))
                self._set_status("재생 서비스를 다시 시작했습니다.")
            else:
                self._set_status(self.client.last_error or "서비스 시작에 실패했습니다.")

        Clock.schedule_once(lambda *a: again(), 1.2)

    def show_log(self):
        try:
            text = config.LOG_FILE.read_text(encoding="utf-8")
            lines = text.splitlines()[-40:]
            self.settings_screen.set_log("\n".join(lines) or "(로그 없음)")
        except Exception:
            self.settings_screen.set_log("(로그 없음)")

    # ---------------------------------------------------------- 시작
    def on_start(self):
        try:
            self._on_start()
        except Exception:
            tb = traceback.format_exc()
            config.log_line("on_start 오류:\n" + tb)
            try:
                self._set_status("시작 오류: " + tb.strip().splitlines()[-1][:120])
            except Exception:
                pass

    def _on_start(self):
        config.log_line("on_start 진입")
        self.refresh_sources()
        self._refresh_mode_buttons()
        # ★ 재생 서비스는 UI 가 다 만들어진 뒤에 별도로 띄운다.
        #   (서비스가 어떤 이유로 죽어도 앱 시작에는 영향이 없도록)
        Clock.schedule_once(lambda *a: self._start_service(), 1.5)
        self.client.send("volume", value=float(self.settings.get("volume", 0.8)))
        self.client.send("repeat", value=self.settings.get("repeat", "all"))
        self.client.send("shuffle", value=bool(self.settings.get("shuffle")))
        self.client.send("infinite", value=bool(self.settings.get("infinite")))
        self.player_screen.sld_vol.value = float(self.settings.get("volume", 0.8)) * 100
        Clock.schedule_once(lambda *a: self._service_check(), 4.0)
        # 처음 실행 시 차트를 자동으로 불러온다
        Clock.schedule_once(lambda *a: self.load_chart(), 0.6)

    def _start_service(self):
        config.log_line("재생 서비스 시작 시도")
        try:
            ok = self.client.start("무한 음악 플레이어", "재생 대기 중")
            config.log_line("재생 서비스 시작 결과: %s %s"
                            % (ok, self.client.last_error))
            if not ok and self.client.last_error:
                self._set_status(self.client.last_error)
        except Exception:
            tb = traceback.format_exc()
            config.log_line("재생 서비스 시작 예외:\n" + tb)
        try:
            self.client.request_notification_permission()
        except Exception:
            pass

    def _service_check(self):
        if not self.client.is_running():
            msg = self.client.last_error or ("재생 서비스가 시작되지 않았습니다. "
                                             "설정 → 서비스 재시작 을 눌러주세요.")
            self._set_status(msg)
            self.head_info.text = "서비스 대기 중"


if __name__ == "__main__":
    MusicApp().run()
