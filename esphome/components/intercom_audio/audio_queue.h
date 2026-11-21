#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>

// Single-producer/single-consumer byte ring. The microphone task (small 4 KB
// stack, not the main loop) only pushes here; the main loop pops and does the
// detection, socket I/O and state publishing, which are neither stack-light
// nor thread-safe.
namespace audioq {

constexpr size_t SIZE = 16384;  // power of two; ~0.5 s of 16 kHz 16-bit audio

class Queue {
 public:
  // Drops the whole chunk (and counts it) when there is no room.
  void push(const uint8_t *data, size_t len) {
    size_t head = head_.load(std::memory_order_relaxed);
    size_t tail = tail_.load(std::memory_order_acquire);
    if (SIZE - (head - tail) < len) {
      dropped_.fetch_add(1, std::memory_order_relaxed);
      return;
    }
    for (size_t i = 0; i < len; i++)
      buf_[(head + i) & (SIZE - 1)] = data[i];
    head_.store(head + len, std::memory_order_release);
  }

  // Copies up to max bytes into out; returns the number copied.
  size_t pop(uint8_t *out, size_t max) {
    size_t tail = tail_.load(std::memory_order_relaxed);
    size_t head = head_.load(std::memory_order_acquire);
    size_t n = head - tail;
    if (n > max)
      n = max;
    for (size_t i = 0; i < n; i++)
      out[i] = buf_[(tail + i) & (SIZE - 1)];
    tail_.store(tail + n, std::memory_order_release);
    return n;
  }

  uint32_t dropped() const { return dropped_.load(std::memory_order_relaxed); }

 private:
  uint8_t buf_[SIZE];
  std::atomic<size_t> head_{0}, tail_{0};
  std::atomic<uint32_t> dropped_{0};
};

inline Queue instance;

}  // namespace audioq
