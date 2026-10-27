// Spotify lyrics display - v8 (font mode)
// Adafruit ESP32-S2 TFT Feather (240x135)
//
// The board draws the text itself with its own fonts. The two font files in
// this folder (cjk_font_24.h and cjk_font_12.h) contain every common Chinese
// character - Traditional AND Simplified (about 21,000) - plus English.
//
// Messages from spotify_lyrics_font.py (one per line, UTF-8 text):
//   T,song - artist   -> title (top, green, 12px)
//   M,current line    -> lyric (white, 24px, up to 3 rows)
//   P,elapsed,total,playing -> time bar (milliseconds; playing is 1 or 0)
//   C,                -> clear the screen
//
// Libraries (Tools > Manage Libraries):
//   Adafruit ST7735 and ST7789 Library
//   Adafruit GFX Library
//   U8g2_for_Adafruit_GFX

#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>
#include <U8g2_for_Adafruit_GFX.h>
#include "cjk_font_24.h"
#include "cjk_font_12.h"

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);
U8G2_FOR_ADAFRUIT_GFX u8g2;

const int SCREEN_W = 240;
const int MARGIN = 4;
const int MAX_ROWS = 8;

struct Message {
  char type;
  String text;
};

String message = "";

// ---- Time bar (elapsed time in the song) ----
// Layout of the bottom strip:   1:23 [=========-------] 3:45
const int BAR_Y = 125;           // top of the strip
const int BAR_H = 10;            // height of the strip
const int BAR_X1 = 36;           // left end of the bar
const int BAR_X2 = 204;          // right end of the bar

bool barVisible = false;
bool barPlaying = false;
long barElapsedMs = 0;           // where the song was when Python last told us
long barTotalMs = 0;             // length of the song
unsigned long barStamp = 0;      // millis() when Python told us
unsigned long lastBarDraw = 0;

// Turn milliseconds into "m:ss", e.g. 83000 -> "1:23"
String formatTime(long ms) {
  long s = ms / 1000;
  String secs = String(s % 60);
  if (secs.length() < 2) secs = "0" + secs;
  return String(s / 60) + ":" + secs;
}

void drawBar() {
  if (!barVisible || barTotalMs <= 0) return;

  // Between updates from Python, keep counting with the board's own clock
  long elapsed = barElapsedMs;
  if (barPlaying) elapsed += millis() - barStamp;
  if (elapsed > barTotalMs) elapsed = barTotalMs;

  uint16_t grey = tft.color565(70, 70, 70);
  uint16_t green = tft.color565(30, 215, 96);

  // Times, using the small built-in font (6x8 pixels per letter).
  // Giving setTextColor a background color overwrites the old digits.
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE, ST77XX_BLACK);
  String left = formatTime(elapsed) + " ";
  String right = " " + formatTime(barTotalMs);
  tft.setCursor(2, BAR_Y + 1);
  tft.print(left);
  tft.setCursor(SCREEN_W - 2 - right.length() * 6, BAR_Y + 1);
  tft.print(right);

  // The bar: green for the part already played, grey for the rest
  int width = BAR_X2 - BAR_X1;
  int filled = (long)width * elapsed / barTotalMs;
  tft.fillRect(BAR_X1, BAR_Y + 3, filled, 4, green);
  tft.fillRect(BAR_X1 + filled, BAR_Y + 3, width - filled, 4, grey);
}

// "P,<elapsed ms>,<total ms>,<1 if playing, 0 if paused>"
void handleProgress(const String &text) {
  long elapsed, total;
  int playing;
  if (sscanf(text.c_str(), "%ld,%ld,%d", &elapsed, &total, &playing) != 3) return;
  barElapsedMs = elapsed;
  barTotalMs = total;
  barPlaying = (playing == 1);
  barStamp = millis();
  barVisible = true;
  drawBar();
}

// Remove spaces from the start and end (safe for Chinese text)
String trimSpaces(const String &s) {
  int start = 0, end = s.length();
  while (start < end && s[start] == ' ') start++;
  while (end > start && s[end - 1] == ' ') end--;
  return s.substring(start, end);
}

// Next piece of text for wrapping: a space, an English word,
// or one Chinese character (2-4 bytes in UTF-8).
String nextToken(const String &s, int &pos) {
  unsigned char b = s[pos];
  if (b == ' ') { pos++; return " "; }

  if (b < 0x80) {                                    // English word
    int start = pos;
    while (pos < (int)s.length()) {
      unsigned char c = s[pos];
      if (c == ' ' || c >= 0x80) break;
      pos++;
    }
    return s.substring(start, pos);
  }

  int len = (b >= 0xF0) ? 4 : (b >= 0xE0) ? 3 : 2;   // UTF-8 length from first byte
  int start = pos;
  pos = min(pos + len, (int)s.length());
  return s.substring(start, pos);
}

// Is this token punctuation that shouldn't start a row? (， 。 ！ ？ etc.)
bool noRowStart(const String &t) {
  return t == "," || t == "." || t == "!" || t == "?" ||
         t == "，" || t == "。" || t == "！" || t == "？" || t == "、" ||
         t == "；" || t == "：" || t == "」" || t == "』" || t == "）";
}

int textWidth(const String &s) {
  return u8g2.getUTF8Width(s.c_str());
}

// Draw wrapped, centered text in one area. Long text ends with "..."
// px is the font's size in pixels (24 or 12).
void showText(String text, int y, int height, const uint8_t *font, int px, uint16_t color) {
  tft.fillRect(0, y, SCREEN_W, height, ST77XX_BLACK);
  u8g2.setFont(font);
  u8g2.setForegroundColor(color);

  // Row spacing comes from the font size, not getFontAscent().
  // U8g2 measures "ascent" using the letter A, which is much shorter than a
  // Chinese character, so rows built from it ended up overlapping.
  // A Chinese character reaches about 7/8 of the font size above the line
  // it sits on, and rows need about 1/5 of the size as a gap.
  int ascent = px * 7 / 8;            // 24px -> 21
  int rowHeight = px + px / 5 + 1;    // 24px -> 29, 12px -> 15
  int maxRows = constrain(height / rowHeight, 1, MAX_ROWS);
  int maxWidth = SCREEN_W - 2 * MARGIN;

  // Break into rows
  String rows[MAX_ROWS];
  int rowCount = 0;
  bool fits = true;
  String row = "";
  text = trimSpaces(text);
  int pos = 0;

  while (pos < (int)text.length()) {
    String token = nextToken(text, pos);
    if (row.length() == 0 && token == " ") continue;

    String tryRow = row + token;
    if (textWidth(tryRow) <= maxWidth || (noRowStart(token) && row.length() > 0)) {
      row = tryRow;
      continue;
    }
    row = trimSpaces(row);
    if (row.length() > 0) {
      if (rowCount == maxRows) { fits = false; break; }
      rows[rowCount++] = row;
    }
    row = (token == " ") ? "" : token;

    // A word wider than the screen: cut it into pieces that fit
    while (fits && textWidth(row) > maxWidth) {
      int cut = row.length() - 1;
      while (cut > 1 && textWidth(row.substring(0, cut)) > maxWidth) cut--;
      while (cut > 1 && ((unsigned char)row[cut] & 0xC0) == 0x80) cut--;  // whole character
      if (rowCount == maxRows) { fits = false; break; }
      rows[rowCount++] = row.substring(0, cut);
      row = row.substring(cut);
    }
    if (!fits) break;
  }
  row = trimSpaces(row);
  if (fits && row.length() > 0) {
    if (rowCount == maxRows) fits = false;
    else rows[rowCount++] = row;
  }

  // Too long: end the last row with "..."
  if (!fits && rowCount > 0) {
    String last = rows[rowCount - 1];
    while (last.length() > 0 && textWidth(last + "...") > maxWidth) {
      int cut = last.length() - 1;
      while (cut > 0 && ((unsigned char)last[cut] & 0xC0) == 0x80) cut--;  // whole character
      last = last.substring(0, cut);
    }
    rows[rowCount - 1] = trimSpaces(last) + "...";
  }

  // Draw, centered (U8g2 draws from the baseline, so add the ascent)
  int startY = y + (height - rowCount * rowHeight) / 2 + ascent;
  for (int i = 0; i < rowCount; i++) {
    int x = max(MARGIN, (SCREEN_W - textWidth(rows[i])) / 2);
    u8g2.drawUTF8(x, startY + i * rowHeight, rows[i].c_str());
  }
}

bool parseMessage(String raw, Message &out) {
  int split = raw.indexOf(',');
  if (split != 1) return false;
  out.type = raw[0];
  out.text = raw.substring(split + 1);
  return true;
}

void handleMessage(String raw) {
  Message msg;
  if (!parseMessage(raw, msg)) return;

  if (msg.type == 'T') {
    showText(msg.text, 0, 22, cjk_font_12, 12, ST77XX_GREEN);
  } else if (msg.type == 'M') {
    showText(msg.text, 22, 102, cjk_font_24, 24, ST77XX_WHITE);   // stops above the time bar
  } else if (msg.type == 'P') {
    handleProgress(msg.text);
  } else if (msg.type == 'C') {
    tft.fillScreen(ST77XX_BLACK);
    barVisible = false;
  }
}

void setup() {
  Serial.setRxBufferSize(4096);   // room for incoming text while drawing
  Serial.begin(115200);

  pinMode(TFT_I2C_POWER, OUTPUT);
  digitalWrite(TFT_I2C_POWER, HIGH);
  delay(10);

  pinMode(TFT_BACKLITE, OUTPUT);
  digitalWrite(TFT_BACKLITE, HIGH);

  tft.init(135, 240);
  tft.setRotation(3);
  tft.fillScreen(ST77XX_BLACK);

  u8g2.begin(tft);
  u8g2.setFontMode(1);

  showText("v11 - 等待電腦 等待电脑", 0, 22, cjk_font_12, 12, ST77XX_GREEN);
  showText("繁體 简体 English 測試", 22, 102, cjk_font_24, 24, ST77XX_WHITE);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      handleMessage(message);
      message = "";
    } else if (c != '\r' && message.length() < 1000) {
      message += c;
    }
  }

  // Update the time bar 4 times a second so it moves smoothly
  if (barVisible && barPlaying && millis() - lastBarDraw >= 250) {
    lastBarDraw = millis();
    drawBar();
  }
}
