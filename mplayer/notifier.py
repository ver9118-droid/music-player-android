"""안드로이드 상태바 알림(포그라운드 서비스 알림) 갱신.

p4a 가 만든 포그라운드 서비스 알림은 서비스 프로세스가 만들고,
같은 서비스 프로세스에서만 id 를 다시 찾을 수 있다.
(NotificationManager.getActiveNotifications 로 채널 id "org.kivy.p4a*" 를 찾아
  그 알림을 갱신한다.)

실패해도 재생에는 영향이 없도록 모든 예외를 삼킨다.
"""
from __future__ import annotations

CHANNEL_PREFIX = "org.kivy.p4a"


def _service_context():
    from mplayer.javautil import autoclass
    PythonService = autoclass("org.kivy.android.PythonService")
    svc = PythonService.mService
    if svc is None:
        return None, None
    return svc, svc.getApplicationContext()


def _active_ids(ctx):
    """현재 떠 있는 포그라운드 알림의 (id, channel_id) 목록."""
    try:
        from mplayer.javautil import autoclass
        Context = autoclass("android.content.Context")
        nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE)
        out = []
        for sbn in nm.getActiveNotifications() or []:
            try:
                notif = sbn.getNotification()
                channel = notif.getChannelId() if hasattr(notif, "getChannelId") else ""
            except Exception:
                channel = ""
            out.append((int(sbn.getId()), channel))
        return out
    except Exception:
        return []


def update(title: str, text: str) -> bool:
    """포그라운드 서비스 알림 내용을 바꾼다. 성공하면 True."""
    try:
        from mplayer.javautil import autoclass
        svc, ctx = _service_context()
        if svc is None or ctx is None:
            return False

        target_id = None
        for nid, channel in _active_ids(ctx):
            if channel.startswith(CHANNEL_PREFIX):
                target_id = nid
                break
        if target_id is None:
            return False

        Notification = autoclass("android.app.Notification")
        NotificationManager = autoclass("android.app.NotificationManager")
        Context = autoclass("android.content.Context")
        Build = autoclass("android.os.Build")

        nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE)
        # 알림 채널을 그대로 재사용한다 (없으면 기본값)
        channel_id = CHANNEL_PREFIX
        for nid, chan in _active_ids(ctx):
            if nid == target_id and chan:
                channel_id = chan
                break

        if int(Build.VERSION.SDK_INT) >= 26:
            builder = Notification.Builder(ctx, channel_id)
        else:
            builder = Notification.Builder(ctx)

        icon_id = ctx.getApplicationInfo().icon
        builder.setContentTitle(str(title))
        builder.setContentText(str(text))
        builder.setSmallIcon(icon_id)
        builder.setOngoing(True)
        try:
            Intent = autoclass("android.content.Intent")
            ContextClass = autoclass("android.content.Context")
            PendingIntent = autoclass("android.app.PendingIntent")
            intent = Intent(ctx, ContextClass)
            pi = PendingIntent.getActivity(ctx, 0, intent,
                                           PendingIntent.FLAG_IMMUTABLE
                                           | PendingIntent.FLAG_UPDATE_CURRENT)
            builder.setContentIntent(pi)
        except Exception:
            pass

        nm.notify(target_id, builder.build())
        return True
    except Exception:
        return False


def post_standalone(title: str, text: str) -> bool:
    """별도 알림(현재 재생 곡)을 띄운다. 포그라운드 알림 갱신이 안될 때 사용."""
    try:
        from mplayer.javautil import autoclass
        svc, ctx = _service_context()
        if ctx is None:
            return False
        Notification = autoclass("android.app.Notification")
        NotificationManager = autoclass("android.app.NotificationManager")
        Context = autoclass("android.content.Context")
        Build = autoclass("android.os.Build")

        nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE)
        channel_id = "org.music.infiniteplayer.playing"
        if int(Build.VERSION.SDK_INT) >= 26:
            try:
                NotificationChannel = autoclass("android.app.NotificationChannel")
                chan = NotificationChannel(channel_id, "재생 중", 3)   # IMPORTANCE_LOW
                nm.createNotificationChannel(chan)
            except Exception:
                pass
            builder = Notification.Builder(ctx, channel_id)
        else:
            builder = Notification.Builder(ctx)
        builder.setContentTitle(str(title))
        builder.setContentText(str(text))
        builder.setSmallIcon(ctx.getApplicationInfo().icon)
        builder.setOngoing(True)
        nm.notify(1001, builder.build())
        return True
    except Exception:
        return False


def cancel_standalone() -> None:
    try:
        from mplayer.javautil import autoclass
        svc, ctx = _service_context()
        if ctx is None:
            return
        Context = autoclass("android.content.Context")
        nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE)
        nm.cancel(1001)
    except Exception:
        pass
