// Spotify lyrics display - Adafruit ESP32-S2 TFT Feather (240x135)
//
// Receives one message per line over USB serial from spotify_lyrics.py:
//   T,song - artist     -> title area (top, small, green)
//   M,current line      -> main area (middle, big, white)
//   B,next line         -> bottom area (small, grey)
//   C,                  -> clear all three areas
//
// Libraries: Adafruit ST7735 and ST7789 Library, Adafruit GFX Library

#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

struct Message {
  char type;
  String text;
};

String message = "";

// Draw word-wrapped, centered text inside one area of the screen.
// Rows that don't fit in the area are dropped.
void showText(String text, int y, int height, int size, uint16_t color) {
  tft.fillRect(0, y, 240, height, ST77XX_BLACK);   // erase just this area
  tft.setTextSize(size);
  tft.setTextColor(color);

  int charWidth = 6 * size;           // built-in font is 6px wide at size 1
  int maxChars = 240 / charWidth;     // letters that fit across
  int rowHeight = 8 * size + 2;       // letter height plus a small gap

  // How many rows fit in this area (at least 1)
  int maxRows = height / rowHeight;
  if (maxRows < 1) maxRows = 1;

  // First pass: break the text into rows
  String rows[8];
  int rowCount = 0;
  String row = "";
  text.trim();

  while (text.length() > 0 && rowCount < maxRows && rowCount < 8) {
    int space = text.indexOf(' ');
    String word;
    if (space == -1) {
      word = text;
      text = "";
    } else {
      word = text.substring(0, space);
      text = text.substring(space + 1);
    }

    if (word.length() == 0) continue;                 // skip double spaces
    if ((int)word.length() > maxChars) {
      word = word.substring(0, maxChars);             // cut very long words
    }

    String tryRow;
    if (row.length() == 0) {
      tryRow = word;
    } else {
      tryRow = row + " " + word;
    }

    if ((int)tryRow.length() <= maxChars) {
      row = tryRow;                                   // it fits, keep it
    } else {
      rows[rowCount] = row;                           // finish this row
      rowCount = rowCount + 1;
      row = word;                                     // start the next one
    }
  }
  if (row.length() > 0 && rowCount < maxRows && rowCount < 8) {
    rows[rowCount] = row;                             // the last row
    rowCount = rowCount + 1;
  }

  // Second pass: draw the rows, centered in the area
  int startY = y + (height - rowCount * rowHeight) / 2;
  for (int i = 0; i < rowCount; i++) {
    int x = (240 - (int)rows[i].length() * charWidth) / 2;
    if (x < 0) x = 0;
    tft.setCursor(x, startY + i * rowHeight);
    tft.print(rows[i]);
  }
}

// Turn "M,some text" into a Message. Returns false if it's not valid.
bool parseMessage(String raw, Message &out) {
  int split = raw.indexOf(',');

  if (split != 1) {
    return false;   // no comma, or it isn't right after the type letter
  }

  out.type = raw[0];
  out.text = raw.substring(split + 1);
  return true;
}

void handleMessage(String raw) {
  Message msg;

  if (!parseMessage(raw, msg)) {
    return;   // bad message, ignore it
  }

  char type = msg.type;
  if (type == 'T') {
    showText(msg.text, 0, 20, 1, ST77XX_GREEN);
  } else if (type == 'M') {
    showText(msg.text, 22, 76, 2, ST77XX_WHITE);
  } else if (type == 'B') {
    showText(msg.text, 100, 35, 1, tft.color565(130, 130, 130));
  } else if (type == 'C') {
    tft.fillScreen(ST77XX_BLACK);
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

  showText("Waiting for computer...", 0, 20, 1, ST77XX_GREEN);
  showText("Run spotify_lyrics.py", 22, 76, 2, ST77XX_WHITE);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n') {
      handleMessage(message);
      message = "";
    } else if (c != '\r' && message.length() < 300) {
      message = message + c;   // cap length so bad data can't fill memory
    }
  }
}
