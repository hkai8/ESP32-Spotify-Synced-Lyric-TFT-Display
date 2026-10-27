// Spotify lyrics display - v7 (picture mode)
// Adafruit ESP32-S2 TFT Feather (240x135)
//
// The board doesn't need any fonts anymore. Your Mac draws each line of text
// (using the Mac's own Chinese fonts, which have every character) into a
// small black-and-white picture, and sends the picture here. The board just
// copies it onto the screen. So no character can ever be missing.
//
// Messages (one per line, from spotify_lyrics_cn.py):
//   C,                         -> clear the screen
//   I,<y>,<height>,<color>,<hex>  -> draw a 240-pixel-wide picture at row y
//      <hex> is the picture: 1 bit per pixel, 30 bytes per row, written as hex
//
// Libraries: Adafruit ST7735 and ST7789 Library, Adafruit GFX Library

#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

const int SCREEN_W = 240;
const int SCREEN_H = 135;
const int ROW_BYTES = SCREEN_W / 8;            // 30 bytes = 240 pixels

struct Message {
  char type;     // 'C' or 'I'
  char *body;    // everything after "X,"
};

// Incoming message buffer. A full-screen picture is 30 * 135 = 4050 bytes,
// which is 8100 hex characters, so leave plenty of room.
const int MAX_MSG = 9000;
char msgBuf[MAX_MSG];
int msgLen = 0;
bool msgTooLong = false;

uint8_t picture[ROW_BYTES * SCREEN_H];        // the decoded picture

// Turn one hex character ('0'-'9', 'a'-'f') into its value 0-15.
// Returns -1 if it isn't a hex character.
int hexValue(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

// Read a number from p, then skip the comma after it.
// Returns false if there's no comma (the message is broken).
bool readNumber(char *&p, long &out) {
  char *end;
  out = strtol(p, &end, 10);
  if (end == p || *end != ',') return false;
  p = end + 1;
  return true;
}

// "I,<y>,<height>,<color>,<hex>"
void drawPicture(char *p) {
  long y, height, color;
  if (!readNumber(p, y) || !readNumber(p, height) || !readNumber(p, color)) return;
  if (y < 0 || height <= 0 || y + height > SCREEN_H) return;

  int bytes = ROW_BYTES * height;
  if ((int)strlen(p) != bytes * 2) {
    // Wrong length means some data got lost on the way.
    // Skip it instead of drawing a broken picture.
    Serial.println("bad picture length, skipped");
    return;
  }

  for (int i = 0; i < bytes; i++) {
    int hi = hexValue(p[2 * i]);
    int lo = hexValue(p[2 * i + 1]);
    if (hi < 0 || lo < 0) return;   // garbage in the data, skip
    picture[i] = (hi << 4) | lo;
  }

  tft.fillRect(0, y, SCREEN_W, height, ST77XX_BLACK);           // erase the area
  tft.drawBitmap(0, y, picture, SCREEN_W, height, (uint16_t)color);  // draw the 1-bits
}

bool parseMessage(char *raw, Message &out) {
  if (raw[0] == 0 || raw[1] != ',') return false;
  out.type = raw[0];
  out.body = raw + 2;
  return true;
}

void handleMessage(char *raw) {
  Message msg;
  if (!parseMessage(raw, msg)) return;

  if (msg.type == 'C') {
    tft.fillScreen(ST77XX_BLACK);
  } else if (msg.type == 'I') {
    drawPicture(msg.body);
  }
}

void setup() {
  Serial.setRxBufferSize(4096);   // room for incoming data while we draw
  Serial.begin(115200);

  pinMode(TFT_I2C_POWER, OUTPUT);
  digitalWrite(TFT_I2C_POWER, HIGH);
  delay(10);

  pinMode(TFT_BACKLITE, OUTPUT);
  digitalWrite(TFT_BACKLITE, HIGH);

  tft.init(135, 240);
  tft.setRotation(3);
  tft.fillScreen(ST77XX_BLACK);

  // Startup message uses the built-in English font
  tft.setTextSize(2);
  tft.setTextColor(ST77XX_GREEN);
  tft.setCursor(10, 40);
  tft.print("v7 - Waiting");
  tft.setCursor(10, 70);
  tft.setTextColor(ST77XX_WHITE);
  tft.print("for computer...");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n') {
      if (!msgTooLong) {
        msgBuf[msgLen] = 0;          // end the text so C functions know where it stops
        handleMessage(msgBuf);
      }
      msgLen = 0;
      msgTooLong = false;
    } else if (c != '\r') {
      if (msgLen < MAX_MSG - 1) {
        msgBuf[msgLen++] = c;
      } else {
        msgTooLong = true;           // too big: throw this message away
      }
    }
  }
}
