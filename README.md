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

## Two modes

| | **Font mode** (recommended) | **Picture mode** |
|---|---|---|
| Folder | `font_mode/` | `picture_mode/` |
| How text is drawn | The board draws the text with the built-in Noto Sans CJK fonts | The computer draws each line into a 1-bit picture and sends that |
| Languages | English/Latin + ~21,000 Traditional & Simplified Chinese characters | Any language your computer's font has (incl. Japanese, Korean) |
| Extras | Time bar with elapsed / total time | — |
| Data sent per line | Just the text | ~7 KB per lyric line |
| Python deps | spotipy, requests, pyserial | + pillow |

Use **picture mode** if you listen to Japanese or Korean songs, since the font-mode fonts have no kana or Hangul.

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
   - U8g2_for_Adafruit_GFX *(font mode only)*
3. Tools menu:
   - **Board:** Adafruit Feather ESP32-S2 TFT
   - **USB CDC On Boot:** Enabled
   - **Partition Scheme:** **Huge APP (3MB No OTA/1MB SPIFFS)**. *Font mode needs this.* The two CJK fonts
     take about 2.2 MB, which doesn't fit the default ~1.3 MB app partition.
4. Open and upload either `font_mode/spotify_lyrics_font/spotify_lyrics_font.ino` or
   `picture_mode/spotify_lyrics_display_cn/spotify_lyrics_display_cn.ino`.

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
4. Close the Arduino Serial Monitor (only one program can use the port), then run the script for the
   sketch you uploaded:
   ```sh
   python3 font_mode/spotify_lyrics_font.py      # font mode
   python3 picture_mode/spotify_lyrics_cn.py     # picture mode
   ```
   The first time it runs, a browser opens so you can log in to Spotify.

The script finds the board automatically on macOS, Linux and Windows. If it picks the wrong port,
set `SERIAL_PORT` near the top of the script.

Picture mode looks for a Chinese-capable font automatically (PingFang on macOS, Microsoft YaHei on Windows,
Noto Sans CJK on Linux: `sudo apt install fonts-noto-cjk`). To use a different font, set `FONT_PATH`.

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

One message per line, `\n`-terminated.

**Font mode** (UTF-8 text)
```
C,                          clear screen
T,<title>                   title bar (12 px, green)
M,<lyric>                   current lyric (24 px, white, up to 3 rows)
P,<elapsed ms>,<total ms>,<1|0>   time bar (playing / paused)
```

**Picture mode**
```
C,                          clear screen
I,<y>,<height>,<rgb565>,<hex>     240-px-wide 1-bit bitmap, 30 bytes per row, MSB first
```

## Repository layout

```
font_mode/
  spotify_lyrics_font.py                 computer side
  spotify_lyrics_font/
    spotify_lyrics_font.ino              board side
    cjk_font_12.h, cjk_font_24.h         U8g2 fonts (Noto Sans CJK TC)
picture_mode/
  spotify_lyrics_cn.py                   computer side
  spotify_lyrics_display_cn/
    spotify_lyrics_display_cn.ino        board side
legacy/                                  earlier English-only sketches (built-in 6x8 font)
```

## Notes

- Lyrics come from LRCLIB, a free community database, so some songs have no synced lyrics. The script
  only accepts a match whose song length is within a few seconds of the Spotify track. If there's no
  good match it shows "no synced lyrics found" rather than another song's lyrics.
- Fonts: `cjk_font_12.h` and `cjk_font_24.h` are made from
  [Noto Sans CJK](https://github.com/notofonts/noto-cjk) with U8g2's `bdfconv`. Noto Sans CJK is licensed
  under the [SIL Open Font License 1.1](https://openfontlicense.org).
