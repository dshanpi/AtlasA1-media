// SPDX-License-Identifier: MIT
#include "media/mojo/services/cedar_video_decoder.h"

#include <dlfcn.h>
#include <errno.h>
#include <atomic>
#include <memory>
#include <vector>

#include "base/functional/bind.h"
#include "base/task/thread_pool.h"
#include "base/threading/platform_thread.h"
#include "base/time/time.h"
#include "media/base/decoder_buffer.h"
#include "media/base/video_frame.h"

extern "C" {
#include "media/mojo/services/cedar_client.h"
}

namespace media {
namespace {
struct Api {
  decltype(&t736_client_available) available = nullptr;
  decltype(&t736_client_open) open = nullptr;
  decltype(&t736_client_push) push = nullptr;
  decltype(&t736_client_pull) pull = nullptr;
  decltype(&t736_client_drain) drain = nullptr;
  decltype(&t736_client_flush) flush = nullptr;
  decltype(&t736_client_close) close = nullptr;
  Api() {
#define LOAD(n) n = reinterpret_cast<decltype(n)>(dlsym(RTLD_DEFAULT, "t736_client_" #n))
    LOAD(available); LOAD(open); LOAD(push); LOAD(pull);
    LOAD(drain); LOAD(flush); LOAD(close);
#undef LOAD
  }
  bool Ready() const {
    return available && open && push && pull && drain && flush && close &&
           available() == 1;
  }
};
const Api& Client() { static const Api api; return api; }
// The v2 client connection carries one hardware context. A second player must
// fall back rather than flush or close the first player's context.
std::atomic<bool> leased{false};
using Code = DecoderStatus::Codes;
}  // namespace

struct CedarVideoDecoder::Result {
  DecoderStatus status = Code::kOk;
  std::vector<scoped_refptr<VideoFrame>> frames;
  bool eos = false;
};

class CedarVideoDecoder::Worker {
 public:
  ~Worker() { Close(); }
  DecoderStatus Initialize(VideoDecoderConfig config, bool low_delay) {
    Close();
    if (low_delay || config.is_encrypted() || !config.IsValidConfig() ||
        config.alpha_mode() != VideoDecoderConfig::AlphaMode::kIsOpaque ||
        (config.coded_size().width() & 1) ||
        (config.coded_size().height() & 1) ||
        !IsVideoDecoderConfigSupported(SupportedConfigs(), config))
      return Code::kUnsupportedConfig;
    if (!Available()) return Code::kFailedToCreateDecoder;
    bool expected = false;
    if (!leased.compare_exchange_strong(expected, true))
      return Code::kTooManyDecoders;
    owns_lease_ = true;
    config_ = config;
    session_ = Client().open(config.codec() == VideoCodec::kH264
                                ? T736_CODEC_H264 : T736_CODEC_HEVC,
                            config.coded_size().width(),
                            config.coded_size().height());
    if (session_ <= 0) { Close(); return Code::kFailedToCreateDecoder; }
    return Code::kOk;
  }

  Result Decode(scoped_refptr<DecoderBuffer> buffer) {
    Result result;
    if (session_ <= 0) { result.status = Code::kNotInitialized; return result; }
    const auto deadline = base::TimeTicks::Now() + base::Seconds(5);
    if (buffer->end_of_stream()) {
      if (Client().drain(session_) < 0) {
        result.status = Code::kPlatformDecodeFailure;
        return result;
      }
      while (!result.eos && result.status.is_ok()) {
        Receive(result, 10);
        if (base::TimeTicks::Now() >= deadline) {
          result.status = Code::kPlatformDecodeFailure;
          break;
        }
      }
      return result;
    }
    if (!buffer->size() || buffer->size() > T736_MAX_PACKET ||
        buffer->decrypt_config()) {
      result.status = Code::kMalformedBitstream;
      return result;
    }
    int status;
    do {
      status = Client().push(session_, buffer->data(), buffer->size(),
                             buffer->timestamp().InMicroseconds(),
                             buffer->timestamp().InMicroseconds());
      if (status != -EAGAIN) break;
      Receive(result, 5);
      if (!result.status.is_ok()) return result;
    } while (base::TimeTicks::Now() < deadline);
    if (status < 0) result.status = Code::kPlatformDecodeFailure;
    if (result.status.is_ok()) Receive(result, 0);
    return result;
  }

  Result Poll() { Result result; if (session_ > 0) Receive(result, 0); return result; }
  void Reset() { if (session_ > 0 && Client().flush(session_) < 0) Close(); }

 private:
  void Close() {
    if (session_ > 0) Client().close(session_);
    session_ = 0;
    pixels_.reset();
    if (owns_lease_) leased.store(false);
    owns_lease_ = false;
  }
  void Receive(Result& result, unsigned wait_ms) {
    // Bound output buffering even if the peer behaves incorrectly. The broker
    // validates dimensions and lengths before copying into this allocation.
    for (int count = 0; count < 8; ++count) {
      if (result.frames.size() >= 64) {
        result.status = Code::kPlatformDecodeFailure; return;
      }
      if (!pixels_)
        pixels_ = std::make_unique<std::vector<uint8_t>>(
            config_.coded_size().GetArea() * 3 / 2);
      t736_frame picture{};
      int status = Client().pull(session_, pixels_->data(), pixels_->size(),
                                 &picture, count == 0 ? wait_ms : 0);
      if (status == 0) return;
      if (status == 2) { result.eos = true; return; }
      if (status != 1) { result.status = Code::kPlatformDecodeFailure; return; }
      gfx::Size size(picture.width, picture.height);
      if (size != config_.coded_size() ||
          picture.bytes_written != pixels_->size()) {
        result.status = Code::kPlatformDecodeFailure; return;
      }
      auto frame = VideoFrame::WrapExternalData(
          PIXEL_FORMAT_I420, size, config_.visible_rect(), config_.natural_size(),
          base::span<const uint8_t>(*pixels_), base::Microseconds(picture.pts_us));
      if (!frame) { result.status = Code::kFailedToGetVideoFrame; return; }
      frame->AddDestructionObserver(base::BindOnce(
          [](std::unique_ptr<std::vector<uint8_t>>) {}, std::move(pixels_)));
      frame->set_color_space(config_.color_space_info().ToGfxColorSpace());
      frame->metadata().power_efficient = true;
      result.frames.push_back(std::move(frame));
    }
  }
  int session_ = 0;
  bool owns_lease_ = false;
  VideoDecoderConfig config_;
  std::unique_ptr<std::vector<uint8_t>> pixels_;
};

bool CedarVideoDecoder::Available() {
  return Client().Ready();
}
SupportedVideoDecoderConfigs CedarVideoDecoder::SupportedConfigs() {
  SupportedVideoDecoderConfigs configs;
  for (auto profile : {H264PROFILE_BASELINE, H264PROFILE_MAIN,
                       H264PROFILE_HIGH, HEVCPROFILE_MAIN})
    configs.emplace_back(profile, profile, gfx::Size(16,16),
                         gfx::Size(3840,2160), false, false);
  return configs;
}
CedarVideoDecoder::CedarVideoDecoder()
    : worker_(base::ThreadPool::CreateSequencedTaskRunner(
          {base::MayBlock(), base::TaskPriority::USER_VISIBLE})) {}
CedarVideoDecoder::~CedarVideoDecoder() {
  if (decode_cb_) std::move(decode_cb_).Run(Code::kAborted);
}
void CedarVideoDecoder::Initialize(const VideoDecoderConfig& config, bool low_delay,
    CdmContext*, InitCB callback, const OutputCB& output, const WaitingCB&) {
  poll_timer_.Stop();
  weak_factory_.InvalidateWeakPtrs();
  initialized_ = failed_ = false;
  output_cb_ = output;
  worker_.AsyncCall(&Worker::Initialize).WithArgs(config, low_delay).Then(
      base::BindOnce(&CedarVideoDecoder::OnInitialized,
                     weak_factory_.GetWeakPtr(), std::move(callback)));
}
void CedarVideoDecoder::OnInitialized(InitCB callback, DecoderStatus status) {
  initialized_ = status.is_ok();
  std::move(callback).Run(std::move(status));
}
void CedarVideoDecoder::Decode(scoped_refptr<DecoderBuffer> buffer, DecodeCB cb) {
  CHECK(!decode_cb_);
  poll_timer_.Stop();
  decode_cb_ = std::move(cb);
  worker_.AsyncCall(&Worker::Decode).WithArgs(std::move(buffer)).Then(
      base::BindOnce(&CedarVideoDecoder::OnDecoded, weak_factory_.GetWeakPtr()));
}
void CedarVideoDecoder::Deliver(Result& result) {
  if (!result.status.is_ok()) failed_ = true;
  for (auto& frame : result.frames) output_cb_.Run(std::move(frame));
}
void CedarVideoDecoder::OnDecoded(Result result) {
  Deliver(result);
  if (failed_ && result.status.is_ok()) result.status = Code::kPlatformDecodeFailure;
  if (!result.eos) SchedulePoll();
  std::move(decode_cb_).Run(std::move(result.status));
}
void CedarVideoDecoder::SchedulePoll() {
  if (!initialized_ || failed_ || poll_timer_.IsRunning()) return;
  poll_timer_.Start(FROM_HERE, base::Milliseconds(5), this, &CedarVideoDecoder::Poll);
}
void CedarVideoDecoder::Poll() {
  if (decode_cb_) return;
  worker_.AsyncCall(&Worker::Poll).Then(
      base::BindOnce(&CedarVideoDecoder::OnPolled, weak_factory_.GetWeakPtr()));
}
void CedarVideoDecoder::OnPolled(Result result) {
  Deliver(result);
  if (!result.eos && !decode_cb_) SchedulePoll();
}
void CedarVideoDecoder::Reset(base::OnceClosure done) {
  poll_timer_.Stop();
  weak_factory_.InvalidateWeakPtrs();
  if (decode_cb_) std::move(decode_cb_).Run(Code::kAborted);
  failed_ = false;
  worker_.AsyncCall(&Worker::Reset).Then(std::move(done));
}
bool CedarVideoDecoder::NeedsBitstreamConversion() const { return true; }
bool CedarVideoDecoder::IsPlatformDecoder() const { return true; }
VideoDecoderType CedarVideoDecoder::GetDecoderType() const { return VideoDecoderType::kCedar; }
}  // namespace media
