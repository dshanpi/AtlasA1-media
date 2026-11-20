// SPDX-License-Identifier: MIT
#ifndef MEDIA_MOJO_SERVICES_CEDAR_VIDEO_DECODER_H_
#define MEDIA_MOJO_SERVICES_CEDAR_VIDEO_DECODER_H_

#include "base/memory/weak_ptr.h"
#include "base/threading/sequence_bound.h"
#include "base/timer/timer.h"
#include "media/base/supported_video_decoder_config.h"
#include "media/base/video_decoder.h"

namespace media {
// Candidate broker adapter. No device opens, socket connects or dma-buf imports
// occur here: the opt-in preload establishes the ordinary-memory channel before
// the GPU sandbox starts. Broker failure leaves the software decoder available.
class CedarVideoDecoder final : public VideoDecoder {
 public:
  static bool Available();
  static SupportedVideoDecoderConfigs SupportedConfigs();
  CedarVideoDecoder();
  ~CedarVideoDecoder() override;
  void Initialize(const VideoDecoderConfig&, bool, CdmContext*, InitCB,
                  const OutputCB&, const WaitingCB&) override;
  void Decode(scoped_refptr<DecoderBuffer>, DecodeCB) override;
  void Reset(base::OnceClosure) override;
  bool NeedsBitstreamConversion() const override;
  bool IsPlatformDecoder() const override;
  VideoDecoderType GetDecoderType() const override;

 private:
  struct Result;
  class Worker;
  void OnInitialized(InitCB, DecoderStatus);
  void OnDecoded(Result);
  void Poll();
  void OnPolled(Result);
  void Deliver(Result&);
  void SchedulePoll();
  base::SequenceBound<Worker> worker_;
  OutputCB output_cb_;
  DecodeCB decode_cb_;
  base::OneShotTimer poll_timer_;
  bool initialized_ = false;
  bool failed_ = false;
  base::WeakPtrFactory<CedarVideoDecoder> weak_factory_{this};
};
}  // namespace media
#endif
