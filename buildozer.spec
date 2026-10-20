[app]

# (str) Title of your application
title = 무한 음악 플레이어

# (str) Package name
package.name = infiniteplayer

# (str) Package domain (needed for android/ios packaging)
package.domain = org.music

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,jpeg,kv,atlas,ttf,json,txt,pem

# (list) List of directory to exclude (let empty to not exclude anything)
source.exclude_dirs = .buildozer, bin, .git, .github, __pycache__, tests, .venv, .venv-test, .kivy, tools

# (list) List of exclusions using pattern matching
source.exclude_patterns = *.pyc, *.pyo, *.md, *.log

# (str) Application versioning (method 1)
version = 1.0.0

# (list) Application requirements
#  - yt-dlp : 유튜브 검색/오디오 다운로드 (순수 파이썬)
#  - requests : 차트/가사 HTTP (certifi 로 인증서 처리)
requirements = python3,kivy,pyjnius,openssl,requests,yt-dlp,certifi

# 백그라운드 재생 서비스.
#   :foreground               -> 화면을 나가도 안드로이드가 프로세스를 유지
#   :sticky                   -> 종료돼도 시스템이 다시 띄워줌
#   :foregroundServiceType=mediaPlayback -> 안드로이드 14+ FGS 타입 필수
services = music:services/music.py:foreground:sticky:foregroundServiceType=mediaPlayback

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (list) Permissions
android.permissions = INTERNET,WAKE_LOCK,FOREGROUND_SERVICE,FOREGROUND_SERVICE_MEDIA_PLAYBACK,POST_NOTIFICATIONS,READ_MEDIA_AUDIO

# (str) Icon / presplash
icon.filename = %(source.dir)s/assets/icon.png
icon.adaptive_foreground.filename = %(source.dir)s/assets/icon_fg.png
icon.adaptive_background.filename = %(source.dir)s/assets/icon_bg.png
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #12161d

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (str) Presplash background color (for android toolchain)
#android.presplash_color = #FFFFFF

# (bool) Use a custom service to allow the app to run in the background
android.allow_backup = True

# (int) Target Android API, should be as high as possible.
android.api = 34

# (int) Minimum API your APK / AAB will support.
android.minapi = 24

# (int) Android NDK API to use. This is the minimum API your app will support.
android.ndk_api = 24

# (bool) Use --private data storage (True) or --dir public storage (False)
android.private_storage = True

# (list) The Android archs to build for
android.archs = arm64-v8a

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (bool) Indicate if the build should be in release mode
android.release_artifact = False
