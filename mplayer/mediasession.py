"""안드로이드 MediaSession + 오디오 포커스 관리.

역할
  1) **오디오 포커스** — 통화/다른 앱(유튜브 등)이 소리를 내면 자동으로 일시정지하고,
     그 앱이 끝나면 다시 재생한다. (포커스를 안 잡으면 다른 앱 아래로 계속 소리가 난다)
  2) **MediaSession** — 블루투스 차량/이어폰/락스크린/알림에 곡 정보와
     재생·일시정지·이전·다음 조작을 제공한다. (차량에서 곡 정보가 안 나오던 문제)

전부 try/except 로 감싸 둬서, 실패해도 재생 기능 자체는 계속 동작한다.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

FGS_CHANNEL_PREFIX = "org.kivy.p4a"
PLAY_CHANNEL_ID = "org.music.infiniteplayer.playback"
SESSION_TAG = "InfiniteMusicPlayer"

# AudioManager.OnAudioFocusChangeListener 상수
FOCUS_GAIN = 0
FOCUS_LOSS = 1
FOCUS_LOSS_TRANSIENT = 2
FOCUS_LOSS_TRANSIENT_CAN_DUCK = 3


class MediaController:
    """서비스 프로세스에서 쓰는 MediaSession/오디오 포커스 컨트롤러."""

    def __init__(self, handlers: Optional[Dict[str, Callable]] = None):
        self.ok = False
        self.session = None
        self._ctx = None
        self._svc = None
        self._listener = None
        self._focus_request = None
        self._fgs_id = None
        self._paused_by_focus = False
        self._ducked = False
        self._last_key = None
        self._last_pos = 0
        self._last_update = 0.0
        self._session_failed = False
        self.h = handlers or {}
        try:
            self._build()
        except Exception:
            self.ok = False

    # ------------------------------------------------------------- 초기화
    def _build(self):
        from mplayer.javautil import autoclass
        PythonService = autoclass("org.kivy.android.PythonService")
        svc = PythonService.mService
        if svc is None:
            return
        self._svc = svc
        self._ctx = svc.getApplicationContext()
        self.ok = True

    def _ensure_session(self):
        """MediaSession 을 (최초 재생 시점에) 만든다.

        세션 생성은 실패할 수 있으므로 예외를 삼키고 기능만 끈다.
        앱/서비스 기동에는 영향이 없도록 재생 시작 시점에 한 번만 시도한다.
        """
        if self.session is not None or self._session_failed:
            return self.session is not None
        try:
            from mplayer.javautil import autoclass
            MediaSession = autoclass("android.media.session.MediaSession")
            Callback = autoclass("android.media.session.MediaSession$Callback")
            controller = self

            class SessionCallback(Callback):
                def onPlay(self):
                    controller._fire("play")

                def onPause(self):
                    controller._fire("pause")

                def onSkipToNext(self):
                    controller._fire("next")

                def onSkipToPrevious(self):
                    controller._fire("prev")

                def onSeekTo(self, pos):
                    controller._fire("seek", int(pos))

                def onStop(self):
                    controller._fire("stop")

                def onFastForward(self):
                    controller._fire("next")

                def onRewind(self):
                    controller._fire("prev")

            self.session = MediaSession(self._ctx, SESSION_TAG)
            self.session.setCallback(SessionCallback())
            try:
                self.session.setFlags(4)      # FLAG_HANDLES_MEDIA_BUTTONS
            except Exception:
                pass

            # 알림/차량 화면을 누르면 앱으로 이동
            try:
                Intent = autoclass("android.content.Intent")
                PendingIntent = autoclass("android.app.PendingIntent")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                intent = Intent(self._ctx, PythonActivity)
                intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
                pi = PendingIntent.getActivity(
                    self._ctx, 0, intent,
                    PendingIntent.FLAG_IMMUTABLE |
                    PendingIntent.FLAG_UPDATE_CURRENT)
                self.session.setSessionActivity(pi)
            except Exception:
                pass

            # 알림 채널 (사용자에게 보이게)
            try:
                NotificationChannel = autoclass("android.app.NotificationChannel")
                nm = self._notification_manager()
                chan = NotificationChannel(PLAY_CHANNEL_ID, "재생 중", 3)
                nm.createNotificationChannel(chan)
            except Exception:
                pass
            return True
        except Exception:
            self._session_failed = True
            self.session = None
            return False

    def _notification_manager(self):
        from mplayer.javautil import autoclass
        Context = autoclass("android.content.Context")
        return self._ctx.getSystemService(Context.NOTIFICATION_SERVICE)

    def _fire(self, name, *args):
        fn = self.h.get(name)
        if not fn:
            return
        try:
            fn(*args)
        except Exception:
            pass

    # ------------------------------------------------------------- 오디오 포커스
    def request_focus(self):
        """오디오 포커스를 요청한다(통화/다른 앱이 소리를 내면 포커스를 빼앗김)."""
        if not self.ok:
            return
        try:
            from mplayer.javautil import autoclass
            AudioManager = autoclass("android.media.AudioManager")
            Build = autoclass("android.os.Build")
            controller = self

            class FocusListener:
                def onAudioFocusChange(self, change):
                    controller._on_focus_change(change)

                def __call__(self, change):
                    controller._on_focus_change(change)

            Listener = autoclass("android.media.AudioManager$OnAudioFocusChangeListener")
            self._listener = Listener(FocusListener())
            am = self._ctx.getSystemService(
                autoclass("android.content.Context").AUDIO_SERVICE)

            if int(Build.VERSION.SDK_INT) >= 26:
                AudioAttributes = autoclass("android.media.AudioAttributes")
                AudioFocusRequest = autoclass("android.media.AudioFocusRequest")
                attrs = AudioAttributes.Builder() \
                    .setUsage(AudioAttributes.USAGE_MEDIA) \
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC) \
                    .build()
                req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN) \
                    .setAudioAttributes(attrs) \
                    .setOnAudioFocusChangeListener(self._listener) \
                    .build()
                self._focus_request = req
                am.requestAudioFocus(req)
            else:
                am.requestAudioFocus(self._listener, AudioManager.STREAM_MUSIC,
                                     AudioManager.AUDIOFOCUS_GAIN)
            self._register_noisy(am, autoclass)
        except Exception:
            self._focus_request = None

    def _register_noisy(self, am, autoclass):
        """이어폰 뽑기(NOISE) 시 일시정지."""
        try:
            Build = autoclass("android.os.Build")
            if int(Build.VERSION.SDK_INT) < 26:
                return
            controller = self

            class NoisyListener:
                def onAudioPlaybackConfigChange(self, config):
                    if int(config) == 1:      # AUDIO_PLAYBACK_CONFIG_NOISY
                        controller._fire("noise")

                def __call__(self, config):
                    if int(config) == 1:
                        controller._fire("noise")

            Cb = autoclass("android.media.AudioManager$OnAudioPlaybackConfigurationChangeListener")
            am.registerAudioPlaybackCallback(Cb(NoisyListener()))
        except Exception:
            pass

    def abandon_focus(self):
        if not self.ok:
            return
        try:
            from mplayer.javautil import autoclass
            AudioManager = autoclass("android.media.AudioManager")
            am = self._ctx.getSystemService(
                autoclass("android.content.Context").AUDIO_SERVICE)
            if self._focus_request is not None:
                am.abandonAudioFocusRequest(self._focus_request)
                self._focus_request = None
            elif self._listener is not None:
                am.abandonAudioFocus(self._listener)
        except Exception:
            pass

    def _on_focus_change(self, change):
        """오디오 포커스 변화 → 재생 일시정지/재개."""
        try:
            if change == FOCUS_LOSS:
                self._paused_by_focus = False
                self._fire("focus_loss")
            elif change == FOCUS_LOSS_TRANSIENT:
                self._paused_by_focus = True
                self._fire("focus_loss_transient")
            elif change == FOCUS_LOSS_TRANSIENT_CAN_DUCK:
                self._ducked = True
                self._fire("duck", True)
            elif change == FOCUS_GAIN:
                self._ducked = False
                self._fire("duck", False)
                if self._paused_by_focus:
                    self._paused_by_focus = False
                    self._fire("focus_gain")
        except Exception:
            pass

    # ------------------------------------------------------------- 상태 갱신
    def update(self, title="", artist="", album="", duration_ms=0,
               position_ms=0, playing=False, artwork=None):
        """곡 정보/재생 상태를 MediaSession 과 알림에 반영한다."""
        if not self.ok:
            return
        if not self._ensure_session():
            return
        try:
            from mplayer.javautil import autoclass
            MediaMetadata = autoclass("android.media.MediaMetadata")
            PlaybackState = autoclass("android.media.session.PlaybackState")

            builder = MediaMetadata.Builder()
            if title:
                builder.putString(MediaMetadata.METADATA_KEY_TITLE, title)
            if artist:
                builder.putString(MediaMetadata.METADATA_KEY_ARTIST, artist)
            if album:
                builder.putString(MediaMetadata.METADATA_KEY_ALBUM, album)
            if duration_ms > 0:
                builder.putLong(MediaMetadata.METADATA_KEY_DURATION, int(duration_ms))
            if artwork:
                try:
                    BitmapFactory = autoclass("android.graphics.BitmapFactory")
                    bmp = BitmapFactory.decodeFile(str(artwork))
                    if bmp is not None:
                        builder.putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, bmp)
                except Exception:
                    pass
            self.session.setMetadata(builder.build())

            state = (PlaybackState.STATE_PLAYING if playing
                     else PlaybackState.STATE_PAUSED)
            ps = PlaybackState.Builder()
            ps.setState(state, int(position_ms), 1.0)
            ps.setActions(PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE |
                          PlaybackState.ACTION_PLAY_PAUSE |
                          PlaybackState.ACTION_SKIP_TO_NEXT |
                          PlaybackState.ACTION_SKIP_TO_PREVIOUS |
                          PlaybackState.ACTION_SEEK_TO |
                          PlaybackState.ACTION_STOP)
            self.session.setPlaybackState(ps.build())
            self.session.setActive(True)
        except Exception:
            pass

    def _find_fgs_id(self):
        """p4a 가 만든 포그라운드 서비스 알림의 id 를 찾는다."""
        if self._fgs_id is not None:
            return self._fgs_id
        try:
            nm = self._notification_manager()
            for sbn in (nm.getActiveNotifications() or []):
                notif = sbn.getNotification()
                channel = ""
                try:
                    channel = notif.getChannelId()
                except Exception:
                    channel = ""
                if channel.startswith(FGS_CHANNEL_PREFIX):
                    self._fgs_id = int(sbn.getId())
                    return self._fgs_id
        except Exception:
            pass
        return None

    def post_notification(self, title="", artist="", artwork=None):
        """포그라운드 알림을 MediaStyle 로 교체한다.

        p4a 가 만든 알림을 그대로 대체하므로 알림이 2 개 뜨지 않는다.
        """
        if not self.ok:
            return
        if not self._ensure_session():
            return
        try:
            from mplayer.javautil import autoclass
            Build = autoclass("android.os.Build")
            Notification = autoclass("android.app.Notification")
            Style = autoclass("android.app.Notification$MediaStyle")
            builder = Notification.Builder(self._ctx, PLAY_CHANNEL_ID)
            if int(Build.VERSION.SDK_INT) < 26:
                builder = Notification.Builder(self._ctx)
            builder.setContentTitle(title or "무한 음악 플레이어")
            builder.setContentText(artist or "")
            builder.setSmallIcon(self._ctx.getApplicationInfo().icon)
            builder.setOngoing(True)
            builder.setShowWhen(False)
            try:
                builder.setStyle(Style().setMediaSession(self.session.getSessionToken()))
            except Exception:
                pass
            if artwork:
                try:
                    BitmapFactory = autoclass("android.graphics.BitmapFactory")
                    bmp = BitmapFactory.decodeFile(str(artwork))
                    if bmp is not None:
                        builder.setLargeIcon(bmp)
                except Exception:
                    pass
            notification = builder.build()

            fid = self._find_fgs_id()
            if fid is not None and self._svc is not None:
                self._svc.startForeground(fid, notification)
            else:
                nm = self._notification_manager()
                nm.notify(1002, notification)
        except Exception:
            pass

    def clear_notification(self):
        try:
            nm = self._notification_manager()
            nm.cancel(1002)
        except Exception:
            pass

    def release(self):
        self.abandon_focus()
        try:
            if self.session is not None:
                self.session.setActive(False)
                self.session.release()
                self.session = None
        except Exception:
            pass
        self.ok = False
