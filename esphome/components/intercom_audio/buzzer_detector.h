#pragma once

// Bitron MV80-ish intercom buzzer detector.
//
// Pure C++ (no ESPHome dependencies) so the exact same code runs on the
// device and in tests/buzzer_test.cpp against recorded audio.
//
// Approach (derived from recordings of the real buzzer, see README):
// the buzzer is a set of narrow tones at ~406, ~703, ~2109 and ~2812 Hz that
// alternate every ~100 ms, so no single short window contains all of them.
// The level also varies by ~25 dB depending on where the microphone is, and
// the quiet room is dominated by sub-100 Hz rumble. So instead of comparing
// band energy to total energy or to a fixed loudness gate, we measure how far
// each tone stands out ("prominence", in dB) above the spectrum immediately
// around it, using power spectra averaged over ~270 ms. Broadband noise and
// speech have no isolated peaks at these frequencies; the buzzer always has
// 703 Hz (its strongest tone) plus at least two of the other three. Requiring
// 703 Hz also rejects harmonic series of 406 Hz, which hit the other bands.
//
// 16 kHz, 512 sample window (32 ms, 31.25 Hz bins), 50% overlap (16 ms hop).
// Tone bins: 12-14 (~406 Hz), 21-24 (~703 Hz), 66-68 (~2109 Hz), 89-91 (~2812 Hz).

#include <cmath>
#include <cstdint>
#include <cstring>

namespace buzzer {

constexpr int N = 512;
constexpr int HOP = 256;
constexpr float PI = 3.14159265359f;

constexpr int NUM_TONES = 4;
constexpr int AVG_WINDOWS = 16;  // ~272 ms of overlapped windows
constexpr float MIN_PROMINENCE_DB = 16.0f;
// Noise floor added to both sides of the prominence ratio: white noise of
// ~2 LSB RMS (Hann window power gain 3N/8). Below this a spectrum is "silence",
// which keeps digital silence and synthetic noise-free tones from scoring.
constexpr float FLOOR_LSB = 2.0f;
constexpr float FLOOR_POWER = (float) AVG_WINDOWS * (3.0f * N / 8.0f) * FLOOR_LSB * FLOOR_LSB;
constexpr int TONE_REQUIRED = 1;  // index of the 703 Hz tone, which must always be prominent
constexpr int MIN_TONES = 3;      // of NUM_TONES (including the required one) simultaneously prominent
constexpr int HIT_COUNT_ON = 3;
constexpr uint32_t HIT_GAP_RESET_MS = 500;

// Publishing only: metrics are published while the room is louder than this
// or the signal matches; detection itself is not level-gated.
constexpr float ACTIVE_RMS_DB = -50.0f;
constexpr uint32_t LOUD_DEBUG_MS = 250;
constexpr uint32_t METRIC_HOLD_MS = 10000;

constexpr int TONE_LO[NUM_TONES] = {12, 21, 66, 89};
constexpr int TONE_HI[NUM_TONES] = {14, 24, 68, 91};
// Reference ("surrounding spectrum") bins sit 4..8 bins either side of the tone,
// stored interleaved: below, above, below, above, ...
constexpr int REF_NEAR = 4;
constexpr int REF_FAR = 8;
constexpr int REF_PER_TONE = 2 * (REF_FAR - REF_NEAR + 1);
constexpr int MAX_TONE_BINS = 4;

// Distinct bins analysed per window: tone bins + reference bins per tone.
constexpr int BINS_PER_TONE = MAX_TONE_BINS + REF_PER_TONE;
constexpr int NUM_BINS = NUM_TONES * BINS_PER_TONE;

struct Result {
  bool gated = false;  // window quieter than ACTIVE_RMS_DB (informational)
  bool buzzy = false;  // averaged spectrum matched the buzzer signature
  bool detected = false;
  bool publish_metrics = false;
  bool publish_nan = false;
  float rms_db = 0;
  float prom[NUM_TONES] = {0, 0, 0, 0};  // dB above surrounding spectrum
  float score = 0;                       // weakest prominence that must pass (dB)
  float r407 = 0, r703 = 0, rhigh = 0;   // prom[0], prom[1], max(prom[2], prom[3])
};

class Detector {
 public:
  Detector() {
    for (int t = 0; t < NUM_TONES; t++) {
      int b = t * BINS_PER_TONE;
      for (int k = 0; k < MAX_TONE_BINS; k++)
        bins_[b + k] = (TONE_LO[t] + k <= TONE_HI[t]) ? TONE_LO[t] + k : -1;
      int r = b + MAX_TONE_BINS;
      for (int o = REF_NEAR; o <= REF_FAR; o++) {
        bins_[r++] = TONE_LO[t] - o;
        bins_[r++] = TONE_HI[t] + o;
      }
    }
    for (int j = 0; j < N; j++)
      hann_[j] = 0.5f * (1.0f - cosf(2.0f * PI * (float) j / (float) (N - 1)));
    for (int i = 0; i < NUM_BINS; i++)
      coeff_[i] = bins_[i] < 0 ? 0.0f : 2.0f * cosf(2.0f * PI * (float) bins_[i] / (float) N);
  }

  // Feed one sample. Returns true when a window was analyzed; result is in `out`.
  bool push(int16_t sample, uint32_t now, Result &out) {
    buf_[pos_++] = sample;
    if (pos_ < N)
      return false;
    analyze(now, out);
    memmove(buf_, buf_ + HOP, (N - HOP) * sizeof(int16_t));
    pos_ = N - HOP;
    return true;
  }

 private:
  void analyze(uint32_t now, Result &out) {
    out = Result();

    float mean = 0.0f;
    for (int j = 0; j < N; j++)
      mean += buf_[j];
    mean /= N;

    float sum_sq = 0.0f;
    for (int j = 0; j < N; j++) {
      float c = (float) buf_[j] - mean;
      sum_sq += c * c;
      win_[j] = c * hann_[j];
    }
    out.rms_db = 20.0f * log10f((sqrtf(sum_sq / N) / 32768.0f) + 1e-12f);
    out.gated = out.rms_db < ACTIVE_RMS_DB;

    // Goertzel for every analysed bin, one pass over the samples.
    float q1[NUM_BINS] = {}, q2[NUM_BINS] = {};
    for (int j = 0; j < N; j++) {
      float s = win_[j];
      for (int i = 0; i < NUM_BINS; i++) {
        float q0 = coeff_[i] * q1[i] - q2[i] + s;
        q2[i] = q1[i];
        q1[i] = q0;
      }
    }

    // Keep the last AVG_WINDOWS power spectra and sum them afresh each time
    // (a running add/subtract would leave float residue after loud events).
    float *slot = ring_[ring_pos_];
    for (int i = 0; i < NUM_BINS; i++)
      slot[i] = bins_[i] < 0 ? 0.0f : q1[i] * q1[i] + q2[i] * q2[i] - coeff_[i] * q1[i] * q2[i];
    for (int i = 0; i < NUM_BINS; i++) {
      float acc = 0.0f;
      for (int w = 0; w < AVG_WINDOWS; w++)
        acc += ring_[w][i];
      sum_[i] = acc;
    }
    ring_pos_ = (ring_pos_ + 1) % AVG_WINDOWS;
    if (filled_ < AVG_WINDOWS)
      filled_++;

    if (filled_ == AVG_WINDOWS) {
      for (int t = 0; t < NUM_TONES; t++) {
        int b = t * BINS_PER_TONE;
        float tone = 0.0f;
        for (int k = 0; k < MAX_TONE_BINS; k++)
          if (bins_[b + k] >= 0 && sum_[b + k] > tone)
            tone = sum_[b + k];
        // Reference = the quieter side's mean, so another tone next door
        // (e.g. 406 Hz below the 703 Hz band) cannot mask a real peak.
        float below = 0.0f, above = 0.0f;
        for (int k = 0; k < REF_PER_TONE; k += 2) {
          below += sum_[b + MAX_TONE_BINS + k];
          above += sum_[b + MAX_TONE_BINS + k + 1];
        }
        float ref = (below < above ? below : above) / (REF_PER_TONE / 2);
        out.prom[t] = 10.0f * log10f((tone + FLOOR_POWER) / (ref + FLOOR_POWER));
      }
    }

    // Score: the weakest prominence that still has to pass, i.e. the lower of the
    // required tone and the (MIN_TONES-1)-th highest of the remaining tones.
    float others[NUM_TONES - 1];
    int n_others = 0;
    for (int t = 0; t < NUM_TONES; t++)
      if (t != TONE_REQUIRED)
        others[n_others++] = out.prom[t];
    for (int a = 0; a < n_others; a++)
      for (int c = a + 1; c < n_others; c++)
        if (others[c] > others[a]) {
          float tmp = others[a];
          others[a] = others[c];
          others[c] = tmp;
        }
    float needed = others[MIN_TONES - 2];
    out.score = out.prom[TONE_REQUIRED] < needed ? out.prom[TONE_REQUIRED] : needed;
    out.buzzy = out.score > MIN_PROMINENCE_DB;
    out.r407 = out.prom[0];
    out.r703 = out.prom[1];
    out.rhigh = out.prom[2] > out.prom[3] ? out.prom[2] : out.prom[3];

    if (out.buzzy) {
      // Matching windows form one sequence while no more than HIT_GAP_RESET_MS apart.
      if (last_buzzy_ms_ == 0 || now - last_buzzy_ms_ > HIT_GAP_RESET_MS)
        hit_count_ = 0;
      last_buzzy_ms_ = now;
      if (hit_count_ < HIT_COUNT_ON)
        hit_count_++;
    } else if (hit_count_ > 0 && now - last_buzzy_ms_ > HIT_GAP_RESET_MS) {
      hit_count_ = 0;
    }
    out.detected = hit_count_ >= HIT_COUNT_ON;

    if (!out.gated || out.buzzy)
      last_candidate_ms_ = now;

    if (out.buzzy || out.detected || (!out.gated && now - last_debug_ms_ > LOUD_DEBUG_MS)) {
      last_debug_ms_ = now;
      metrics_are_nan_ = false;
      out.publish_metrics = true;
    } else if (!out.detected && hit_count_ == 0 && now - last_candidate_ms_ > METRIC_HOLD_MS && !metrics_are_nan_) {
      out.publish_nan = true;
      metrics_are_nan_ = true;
    }
  }

  int16_t buf_[N];
  float win_[N];
  float hann_[N];
  int bins_[NUM_BINS];
  float coeff_[NUM_BINS];
  float ring_[AVG_WINDOWS][NUM_BINS] = {};
  float sum_[NUM_BINS] = {};
  int ring_pos_ = 0;
  int filled_ = 0;
  int pos_ = 0;
  int hit_count_ = 0;
  uint32_t last_buzzy_ms_ = 0;
  uint32_t last_debug_ms_ = 0;
  uint32_t last_candidate_ms_ = 0;
  bool metrics_are_nan_ = false;
};

}  // namespace buzzer
