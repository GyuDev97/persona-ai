# 여기까지만 하자 - 세로 음악 플레이어 템플릿

이 폴더의 `make_music_player_template.jsx`는 After Effects에서 실행하면 캡처와 같은 세로 음악 플레이어 씬을 만듭니다. 생성 후 원하는 위치에 `.aep` 프로젝트로 저장하면 됩니다.

## 실행

1. After Effects를 열고 `파일 > 스크립트 > 스크립트 파일 실행`을 선택합니다.
2. `make_music_player_template.jsx`를 고릅니다.
3. 프로젝트가 열리면 `01_MUSIC_PLAYER_MASTER` 컴포지션을 사용합니다.
4. `컴포지션 > 렌더 큐에 추가` 후 H.264, 1080x1920, 30fps로 내보냅니다.

## 수정 위치

- 제목 / 아티스트 / 가사: 이름이 `TXT` 또는 `LYRIC`로 시작하는 텍스트 레이어
- 커버: `02_COVER_ART` 컴포지션의 `REPLACE - cover image`
- 음원: `AUDIO - 여기까지만 하자`
- 진행바: `Progress - fill (animate width)`와 `Progress - handle` 레이어
- 러닝타임: JSX 상단의 `duration` 값 (현재 5분 23초)

타이틀·아티스트는 0.9초 안에 페이드 인되고, 커버와 배경에는 아주 느린 줌 움직임이 들어가 있습니다. 화면 전체의 화려한 전환 대신, 참고 이미지처럼 정적인 감상 화면 느낌을 유지한 구성입니다.

## 만든 SRT 적용하기

정확한 싱크를 찍은 `여기까지만_하자_lyrics.srt`가 있으면, 기존 AEP를 연 뒤 `01_MUSIC_PLAYER_MASTER`를 선택하고 `apply_srt_lyrics_to_ae.jsx`를 실행하세요. 예상 타이밍으로 만든 `LYRIC` 레이어만 지우고, SRT의 62개 시작·종료 시각으로 교체합니다.

제공받은 전체 가사(62줄)를 넣었습니다. 첫 번째 줄은 실제 보컬 시작 시점인 00:14.00부터 시작합니다. 이후 줄은 05:23 음원 끝까지 이어지도록 배치되어 있습니다. 최종 렌더 전 발음 시작점에 맞춰 `lyricStart` 또는 `lineDuration`을 소폭 조정하세요.

## 소스 경로

스크립트는 다음 첨부 파일을 참조합니다.

- `C:/Users/bgpoi/OneDrive/Desktop/여기까지만 하자.mp3`
- `C:/Users/bgpoi/OneDrive/Desktop/여기까지만 하자.jpeg`

파일 위치를 옮기면 JSX 상단의 `audioFile`, `coverFile` 경로만 바꾸어 다시 실행하세요.
