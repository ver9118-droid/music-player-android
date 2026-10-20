# 무한 음악 플레이어 — 안드로이드 버전

데스크톱 버전(`music-player`)을 **Kivy + python-for-android** 로 포팅한 안드로이드 앱입니다.
멜론/지니/한국대중음악 차트를 불러와 음악을 틀고, **앱을 화면에서 닫아도 계속 재생**됩니다.

## 특징

| 기능 | 설명 |
|---|---|
| **백그라운드 재생** | 안드로이드 **포그라운드 서비스**(별도 프로세스)에서 재생 → 홈 화면/다른 앱/화면 끄기 중에도 계속 재생, 알림 표시 |
| **노래방 가사** | 현재 가사 한 줄을 크게 표시하고 곡에 맞춰 다음 줄로 자동 이동(유튜브 자동자막 타임스탬프 싱크) |
| **차트 소스 19종** | 멜론 TOP100 · 지니 장르차트 10종 · 한국대중음악(유튜브 검색) 8종 |
| **즉시 반응** | 곡을 눌러도 곧바로 재생(다운로드는 백그라운드에서) |
| **자동 이어받기/무한 재생** | 한 곡이 끝나면 다음 곡으로 자동 전환, 목록 끝나면 셔플 재시작 |
| **오프라인 캐시** | 내려받은 오디오는 기기에 저장 → 재접속 없이 재재생 |
| **설정** | 무한 재생 / 셔플 / 반복 모드 / 볼륨 |

## 왜 안드로이드 네이티브 MediaPlayer 를 쓰는가

유튜브 음원은 대부분 `m4a(AAC)` 또는 `webm(opus)` 이고, SDL2_mixer 는 이 포맷을
지원하지 않습니다. mp3 로 변환하려면 안드로이드용 ffmpeg(30MB+) 을 APK 에 넣어야 합니다.
대신 **안드로이드 `MediaPlayer` 를 jnius 로 직접 호출**해서
추가 바이너리 없이 m4a/webm/mp3 를 모두 재생합니다.

## 구조

```
main.py                Kivy UI (차트 / 재생 / 설정)
mplayer/
  config.py            경로·설정 (안드로이드 앱 전용 폴더)
  models.py            Track / Playlist 모델
  sources.py           차트 소스 정의
  chart.py             멜론/지니 차트 파싱
  lyrics.py            가사 조회 + 자막 싱크
  downloader.py        유튜브 검색/다운로드(캐시)
  player.py            안드로이드 MediaPlayer 래퍼(jnius)
  service_client.py    UI ↔ 서비스 통신(파일 IPC)
  favorites.py         즐겨찾기
services/music.py      백그라운드 재생 서비스(별도 프로세스)
```

### 백그라운드 재생 구조

```
[앱 프로세스]                      [서비스 프로세스 (:music)]
   UI (Kivy)  ──svc_cmd_*.json──▶   MusicService 루프
            ◀──svc_state.json───     ├ Downloader (yt-dlp)
                                      └ MediaPlayer (jnius)
```

`buildozer.spec` 의
`services = music:services/music.py:foreground:sticky:foregroundServiceType=mediaPlayback`
선언으로 안드로이드 포그라운드 서비스로 등록합니다.
`mediaPlayback` 타입은 안드로이드 14+ 에서 필수입니다.

## 빌드 (GitHub Actions)

`main` 브랜치에 푸시하면 `ghcr.io/kivy/buildozer` 공식 이미지로 APK 를 만듭니다.
결과물은 `bin/` 에 놓이고 Actions 아티팩트로 올라갑니다.

```bash
git push
gh run watch
```

## 알아두면 좋은 점

- 첫 재생은 유튜브 검색 + 오디오 다운로드가 걸려 수 초~수십 초 걸릴 수 있습니다.
- 유튜브가 정책이나 지역에 따라 접근을 막으면 재생이 안 될 수 있습니다.
- 캐시된 오디오는 앱 전용 폴더(`Android/data/org.music.infiniteplayer/files/cache`)에 쌓입니다.
