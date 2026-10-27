// Spotify lyrics display for Adafruit ESP32-S2 TFT Feather (240x135 ST7789)
// Receives lines over USB serial from spotify_lyrics.py on your computer.
//   S|song title - artist    -> top bar
//   L|current lyric line     -> big text in the middle
//   N|next lyric line        -> small grey text at the bottom
//
// Libraries: Adafruit ST7735 and ST7789 Library, Adafruit GFX Library

#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

const int W = 240;
String inbox = "";

// Draw text word-wrapped and centered inside a horizontal band of the screen
void drawWrapped(String s, int y, int h, uint8_t size, uint16_t color) {
  tft.fillRect(0, y, W, h, ST77XX_BLACK);
  tft.setTextSize(size);
  tft.setTextColor(color);
  tft.setTextWrap(false);

  int charW = 6 * size;
  int lineH = 8 * size + 2;
  int maxChars = W / charW;
  int maxRows = min(h / lineH, 6);

  String rows[6];
  int n = 0;
  String line = "";
  s.trim();

  while (s.length() > 0 && n < maxRows) {
    int sp = s.indexOf(' ');
    String word = (sp < 0) ? s : s.substring(0, sp);
    s = (sp < 0) ? "" : s.substring(sp + 1);
    if ((int)word.length() > maxChars) word = word.substring(0, maxChars);

    String trial = line.length() ? line + " " + word : word;
    if ((int)trial.length() <= maxChars) {
      line = trial;
    } else {
      rows[n++] = line;
      line = word;
    }
  }
  if (line.length() && n < maxRows) rows[n++] = line;

  int startY = y + (h - n * lineH) / 2;
  for (int i = 0; i < n; i++) {
    int x = (W - (int)rows[i].length() * charW) / 2;
    tft.setCursor(max(x, 0), startY + i * lineH);
    tft.print(rows[i]);
  }
}

void handleMessage(const String &msg) {
  if (msg.length() < 2 || msg[1] != '|') return;
  char kind = msg[0];
  String text = msg.substring(2);

  if (kind == 'S') {
    drawWrapped(text, 0, 14, 1, tft.color565(30, 215, 96));   // green title bar
  } else if (kind == 'L') {
    drawWrapped(text, 20, 76, 2, ST77XX_WHITE);               // current line
  } else if (kind == 'N') {
    drawWrapped(text, 100, 34, 1, tft.color565(130, 130, 130)); // next line
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(TFT_I2C_POWER, OUTPUT);
  digitalWrite(TFT_I2C_POWER, HIGH);
  delay(10);

  pinMode(TFT_BACKLITE, OUTPUT);
  digitalWrite(TFT_BACKLITE, HIGH);

  tft.init(135, 240);
  tft.setRotation(3);
  tft.fillScreen(ST77XX_BLACK);

  drawWrapped("Waiting for computer...", 0, 14, 1, tft.color565(30, 215, 96));
  drawWrapped("Run spotify_lyrics.py", 20, 76, 2, ST77XX_WHITE);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      handleMessage(inbox);
      inbox = "";
    } else if (c != '\r' && inbox.length() < 300) {
      inbox += c;
    }
  }
}
