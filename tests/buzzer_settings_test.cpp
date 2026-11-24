#include <cassert>
#include <cmath>
#include <cstdint>

#include "../esphome/components/intercom_audio/buzzer_detector.h"

int main() {
  buzzer::Detector defaults;
  buzzer::Detector high_score(200.0f);
  buzzer::Detector high_2812(buzzer::MIN_PROMINENCE_DB, 200.0f);
  buzzer::Detector many_hits(buzzer::MIN_PROMINENCE_DB, buzzer::MIN_2812_PROMINENCE_DB, 10000);
  buzzer::Detector short_gap(buzzer::MIN_PROMINENCE_DB, buzzer::MIN_2812_PROMINENCE_DB, 3, 1);
  buzzer::Detector one_hit(buzzer::MIN_PROMINENCE_DB, buzzer::MIN_2812_PROMINENCE_DB, 1);
  buzzer::Detector *detectors[] = {&defaults, &high_score, &high_2812, &many_hits, &short_gap, &one_hit};
  uint32_t first_detection[6] = {};
  bool matched[6] = {};

  for (int i = 0; i < 16000; i++) {
    float time = static_cast<float>(i) / 16000.0f;
    float sample = 4000.0f * (sinf(2 * buzzer::PI * 406.25f * time) +
                              sinf(2 * buzzer::PI * 703.125f * time) +
                              sinf(2 * buzzer::PI * 2109.375f * time) +
                              sinf(2 * buzzer::PI * 2812.5f * time));
    for (int d = 0; d < 6; d++) {
      buzzer::Result result;
      uint32_t now = static_cast<uint32_t>(i / 16);
      if (detectors[d]->push(static_cast<int16_t>(sample), now, result)) {
        matched[d] |= result.buzzy;
        if (result.detected && first_detection[d] == 0)
          first_detection[d] = now;
      }
    }
  }

  assert(first_detection[0] != 0);
  assert(!matched[1] && !matched[2]);
  assert(matched[3] && first_detection[3] == 0);
  assert(matched[4] && first_detection[4] == 0);
  assert(first_detection[5] != 0 && first_detection[5] < first_detection[0]);
}
