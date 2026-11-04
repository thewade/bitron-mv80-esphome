// Runs the real detector (esphome/buzzer_detector.h) against WAV files.
//
// usage: buzzer_test <wav> [--expect-detect|--expect-none|--expect-count N] [--verbose]
//
// Accepts 16-bit PCM WAV at 16 kHz or an integer multiple (e.g. 48 kHz);
// decimated with a boxcar average, first channel only.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "../esphome/buzzer_detector.h"

static bool read_wav(const char *path, std::vector<int16_t> &out, uint32_t &rate) {
  FILE *f = fopen(path, "rb");
  if (!f)
    return false;
  uint8_t hdr[12];
  if (fread(hdr, 1, 12, f) != 12 || memcmp(hdr, "RIFF", 4) || memcmp(hdr + 8, "WAVE", 4))
    return false;
  uint16_t ch = 1, bits = 16;
  rate = 0;
  uint8_t ck[8];
  while (fread(ck, 1, 8, f) == 8) {
    uint32_t sz = ck[4] | ck[5] << 8 | ck[6] << 16 | (uint32_t) ck[7] << 24;
    if (!memcmp(ck, "fmt ", 4)) {
      std::vector<uint8_t> d(sz);
      if (fread(d.data(), 1, sz, f) != sz)
        return false;
      ch = d[2] | d[3] << 8;
      rate = d[4] | d[5] << 8 | d[6] << 16 | (uint32_t) d[7] << 24;
      bits = d[14] | d[15] << 8;
    } else if (!memcmp(ck, "data", 4)) {
      if (bits != 16 || !rate)
        return false;
      std::vector<uint8_t> d(sz);
      size_t got = fread(d.data(), 1, sz, f);
      size_t frames = got / (2 * ch);
      out.resize(frames);
      for (size_t i = 0; i < frames; i++)
        out[i] = (int16_t) (d[i * 2 * ch] | d[i * 2 * ch + 1] << 8);
      fclose(f);
      return true;
    } else {
      fseek(f, sz + (sz & 1), SEEK_CUR);
    }
  }
  return false;
}

int main(int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: %s <wav> [--expect-detect|--expect-none|--expect-count N] [--verbose]\n", argv[0]);
    return 2;
  }
  int expect_count = -1;
  int expect = 0;  // 1 = must detect, -1 = must not detect
  bool verbose = false;
  for (int i = 2; i < argc; i++) {
    if (!strcmp(argv[i], "--expect-detect"))
      expect = 1;
    else if (!strcmp(argv[i], "--expect-none"))
      expect = -1;
    else if (!strcmp(argv[i], "--expect-count") && i + 1 < argc)
      expect_count = atoi(argv[++i]);
    else if (!strcmp(argv[i], "--verbose"))
      verbose = true;
  }

  std::vector<int16_t> pcm;
  uint32_t rate;
  if (!read_wav(argv[1], pcm, rate)) {
    fprintf(stderr, "cannot read 16-bit PCM wav: %s\n", argv[1]);
    return 2;
  }
  if (rate % 16000 != 0) {
    fprintf(stderr, "sample rate %u is not a multiple of 16000\n", rate);
    return 2;
  }
  size_t dec = rate / 16000;

  buzzer::Detector det;
  buzzer::Result r;
  size_t windows = 0, buzzy = 0, gated = 0;
  bool ever = false, prev_det = false;
  double first_ms = -1, seg_start = 0, t_ms = 0;
  int segments = 0;
  bool list_segments = true;
  for (size_t i = 0; i + dec <= pcm.size(); i += dec) {
    long acc = 0;
    for (size_t k = 0; k < dec; k++)
      acc += pcm[i + k];
    t_ms = (double) (i / dec) * 1000.0 / 16000.0;
    if (!det.push((int16_t) (acc / (long) dec), (uint32_t) t_ms, r))
      continue;
    windows++;
    buzzy += r.buzzy;
    gated += r.gated;
    if (r.detected && !prev_det)
      seg_start = t_ms;
    if (!r.detected && prev_det) {
      segments++;
      if (list_segments)
        printf("  detected %8.2f s -> %8.2f s (%.2f s)\n", seg_start / 1000, t_ms / 1000, (t_ms - seg_start) / 1000);
    }
    prev_det = r.detected;
    if (r.detected && !ever) {
      ever = true;
      first_ms = t_ms;
    }
    if (verbose)
      printf("%8.1f ms rms=%6.1f dB prom 406=%5.1f 703=%5.1f 2109=%5.1f 2812=%5.1f score=%5.1f %s%s\n", t_ms, r.rms_db,
             r.prom[0], r.prom[1], r.prom[2], r.prom[3], r.score, r.buzzy ? "BUZZY " : "", r.detected ? "DETECTED" : "");
  }

  if (prev_det) {
    segments++;
    printf("  detected %8.2f s -> %8.2f s (still on at end)\n", seg_start / 1000, t_ms / 1000);
  }
  printf("%s: %d detection(s), %zu windows, %zu gated, %zu buzzy, detected=%s", argv[1], segments, windows, gated, buzzy, ever ? "yes" : "no");
  if (ever)
    printf(" (first at %.0f ms)", first_ms);
  printf("\n");

  if (expect_count >= 0 && segments != expect_count) {
    printf("FAIL: expected %d detection(s), got %d\n", expect_count, segments);
    return 1;
  }
  if (expect == 1 && !ever) {
    printf("FAIL: expected detection\n");
    return 1;
  }
  if (expect == -1 && ever) {
    printf("FAIL: unexpected detection\n");
    return 1;
  }
  return 0;
}
