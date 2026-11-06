# ESP32 Spotify Synced Lyric TFT Display

Shows the lyrics of whatever you're playing on Spotify, synced line-by-line, on an
**Adafruit Feather ESP32-S2 TFT** (240×135 ST7789). Traditional Chinese, Simplified Chinese
and English are supported.

A Python script on your computer asks Spotify what's playing and where in the song you are,
gets time-stamped lyrics from [LRCLIB](https://lrclib.net) and sends each line to the board
over USB serial at the right moment.

```
Spotify API ──► Python script (computer) ──USB serial──► Feather ESP32-S2 TFT
LRCLIB      ──►   timing + lyrics                         title / lyric / time bar
```

The board draws the text itself with built-in Noto Sans CJK fonts (12 px and 24 px). They cover English/Latin
and about 21,000 Traditional and Simplified Chinese characters. Japanese kana and Korean Hangul aren't included.
A time bar at the bottom shows elapsed and total time.

## Hardware

- [Adafruit ESP32-S2 TFT Feather](https://www.adafruit.com/product/5300). The
  [ESP32-S3 TFT Feather](https://www.adafruit.com/product/5483) should work too because it uses the same
  `TFT_*` pin names, but it hasn't been tested.
- A USB-C data cable

## Board setup (Arduino IDE)

1. Install the **esp32 by Espressif** boards package (Boards Manager).
2. Install these libraries (Library Manager):
   - Adafruit ST7735 and ST7789 Library
   - Adafruit GFX Library
   - U8g2_for_Adafruit_GFX
3. Tools menu:
   - **Board:** Adafruit Feather ESP32-S2 TFT
   - **USB CDC On Boot:** Enabled
   - **Partition Scheme:** **Huge APP (3MB No OTA/1MB SPIFFS)**. The two CJK fonts take about 2.2 MB,
     which doesn't fit the default ~1.3 MB app partition.
4. Open and upload `font_mode/spotify_lyrics_font/spotify_lyrics_font.ino`.

If the upload doesn't start, hold **BOOT**, tap **RESET**, release **BOOT**, then upload again.

## Computer setup

1. Create an app at the [Spotify developer dashboard](https://developer.spotify.com/dashboard) and add
   `http://127.0.0.1:8888/callback` as a Redirect URI.
2. Install the Python packages:
   ```sh
   pip3 install -r requirements.txt
   ```
3. Put your app's credentials in environment variables (keep them out of the code and out of git):
   ```sh
   export SPOTIPY_CLIENT_ID="your-client-id"
   export SPOTIPY_CLIENT_SECRET="your-client-secret"
   ```
   (Windows PowerShell: `$env:SPOTIPY_CLIENT_ID="..."`)
4. Close the Arduino Serial Monitor (only one program can use the port), then run:
   ```sh
   python3 font_mode/spotify_lyrics_font.py
   ```
   The first time it runs, a browser opens so you can log in to Spotify.

The script finds the board automatically on macOS, Linux and Windows. If it picks the wrong port,
set `SERIAL_PORT` near the top of the script.

## Commands

Type one of these in the terminal while the script runs, then press Enter:

| Key | Action |
|---|---|
| `n` / `p` | next / previous song |
| `r` | restart song |
| `b` / `f` | back / forward 10 s |
| `s` | pause / play |
| `+` / `-` | lyrics are late / early: shift by 0.5 s |
| `q` | quit |

Skip, seek and pause/play need Spotify Premium.

## Serial protocol

One UTF-8 message per line, `\n`-terminated.

```
C,                          clear screen
T,<title>                   title bar (12 px, green)
M,<lyric>                   current lyric (24 px, white, up to 3 rows)
P,<elapsed ms>,<total ms>,<1|0>   time bar (playing / paused)
```

## Repository layout

```
font_mode/
  spotify_lyrics_font.py                 computer side
  spotify_lyrics_font/
    spotify_lyrics_font.ino              board side
    cjk_font_12.h, cjk_font_24.h         U8g2 fonts (Noto Sans CJK TC)
legacy/                                  earlier English-only sketches (built-in 6x8 font)
```

## Notes

- Lyrics come from LRCLIB, a free community database, so some songs have no synced lyrics. The script
  only accepts a match whose song length is within a few seconds of the Spotify track. If there's no
  good match it shows "no synced lyrics found" rather than another song's lyrics.
- Fonts: `cjk_font_12.h` and `cjk_font_24.h` are made from
  [Noto Sans CJK](https://github.com/notofonts/noto-cjk) with U8g2's `bdfconv`. Noto Sans CJK is licensed
  under the [SIL Open Font License 1.1](https://openfontlicense.org).
