#pragma once

// Raw microphone stream for offline testing.
//
// Listens on TCP port 6055, but only while enabled (the "Audio Capture"
// switch, off by default and after every reboot). A client must first send the
// shared token (secrets.yaml: capture_token) within AUTH_TIMEOUT_MS or it is
// dropped; only then does the 16 kHz 16-bit LE mono PCM stream (exactly what
// the detector sees) flow. When disabled the port is closed entirely.
// Chunks are dropped, never blocked on, if the client is slow.
// Use tools/capture.py on the host.

#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <lwip/sockets.h>
#include <string>
#include <unistd.h>

namespace capture {

constexpr uint16_t PORT = 6055;
constexpr uint32_t AUTH_TIMEOUT_MS = 5000;
constexpr size_t MAX_TOKEN = 64;

class Streamer {
 public:
  void set_token(const char *token) { token_ = token; }

  void set_enabled(bool on) {
    enabled_ = on;
    if (!on)
      stop();
  }

  void feed(const uint8_t *data, size_t len, uint32_t now) {
    if (!enabled_ || token_.empty())
      return;
    if (listen_fd_ < 0 && !start())
      return;

    if (client_fd_ < 0) {
      int fd = accept(listen_fd_, nullptr, nullptr);
      if (fd < 0)
        return;
      fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK);
      int one = 1;
      setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
      client_fd_ = fd;
      authed_ = false;
      got_ = 0;
      accepted_ms_ = now;
    }

    if (!authed_) {
      if (now - accepted_ms_ > AUTH_TIMEOUT_MS) {
        drop_client();
        return;
      }
      ssize_t n = recv(client_fd_, rx_ + got_, token_.size() - got_, MSG_DONTWAIT);
      if (n > 0)
        got_ += (size_t) n;
      else if (n == 0 || (errno != EAGAIN && errno != EWOULDBLOCK)) {
        drop_client();
        return;
      }
      if (got_ < token_.size())
        return;
      // Constant-time comparison.
      uint8_t diff = 0;
      for (size_t i = 0; i < token_.size(); i++)
        diff |= (uint8_t) rx_[i] ^ (uint8_t) token_[i];
      if (diff != 0) {
        drop_client();
        return;
      }
      authed_ = true;
      return;
    }

    // All-or-nothing per chunk keeps samples aligned; a drop shows up as a gap.
    ssize_t n = send(client_fd_, data, len, MSG_DONTWAIT);
    if (n == (ssize_t) len)
      return;
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
      dropped_++;
      return;
    }
    if (n >= 0) {
      // Partial write: finish it so the stream stays sample-aligned.
      size_t off = (size_t) n;
      int tries = 0;
      while (off < len && tries++ < 50) {
        ssize_t m = send(client_fd_, data + off, len - off, MSG_DONTWAIT);
        if (m > 0)
          off += (size_t) m;
        else if (m < 0 && errno != EAGAIN && errno != EWOULDBLOCK)
          break;
      }
      if (off == len)
        return;
    }
    drop_client();
  }

  // True only for an authenticated, streaming client.
  bool connected() const { return client_fd_ >= 0 && authed_; }
  uint32_t dropped() const { return dropped_; }

 private:
  bool start() {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0)
      return false;
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    sockaddr_in addr = {};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(PORT);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(fd, (sockaddr *) &addr, sizeof(addr)) < 0 || listen(fd, 1) < 0) {
      close(fd);
      return false;
    }
    fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK);
    listen_fd_ = fd;
    return true;
  }

  void drop_client() {
    if (client_fd_ >= 0)
      close(client_fd_);
    client_fd_ = -1;
    authed_ = false;
    got_ = 0;
  }

  void stop() {
    drop_client();
    if (listen_fd_ >= 0)
      close(listen_fd_);
    listen_fd_ = -1;
  }

  std::string token_;
  char rx_[MAX_TOKEN] = {};
  size_t got_ = 0;
  uint32_t accepted_ms_ = 0;
  bool enabled_ = false;
  bool authed_ = false;
  int listen_fd_ = -1;
  int client_fd_ = -1;
  uint32_t dropped_ = 0;
};

// Single shared instance so other components (switch, status LED) can use it.
inline Streamer instance;

}  // namespace capture
