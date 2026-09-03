---
license: apache-2.0
library_name: onnx
tags:
  - audio
  - audio-tokenizer
  - neural-codec
  - moss-tts-family
  - moss-audio-tokenizer-nano
  - speech-tokenizer
  - onnx
  - onnxruntime
  - browser
---

# MOSS-Audio-Tokenizer-Nano-ONNX

This repository provides the **ONNX exports** of [MOSS-Audio-Tokenizer-Nano](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano), the lightweight audio tokenizer used by [MOSS-TTS-Nano](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano). It is intended for **torch-free** deployment with ONNX Runtime and ONNX Runtime Web.

## Overview

The Nano variant is a lightweight tokenizer with about **20M parameters**, designed to reduce deployment cost while preserving strong perceptual quality.

MOSS-Audio-Tokenizer-Nano supports:

- **48 kHz**, **stereo** audio
- **12.5 Hz** token rate
- **16 RVQ codebooks**
- high-fidelity reconstruction across variable bitrates

This ONNX repository is designed for lightweight inference pipelines such as:

- local CPU deployment with `onnxruntime`
- browser deployment with `onnxruntime-web`
- companion audio encoding/decoding for `MOSS-TTS-Nano-100M-ONNX`

## Supported Backends

| Backend | Runtime | Use Case |
|---------|---------|----------|
| **ONNX Runtime (CPU)** | `onnxruntime` | Local CPU inference |
| **ONNX Runtime Web** | `onnxruntime-web` | Browser-based deployment |

## Repository Contents

| File | Description |
|------|-------------|
| `moss_audio_tokenizer_encode.onnx` | Encoder graph for waveform -> discrete audio codes |
| `moss_audio_tokenizer_encode.data` | External weights for the encoder graph |
| `moss_audio_tokenizer_decode_full.onnx` | Full decoder graph for audio codes -> waveform |
| `moss_audio_tokenizer_decode_step.onnx` | Streaming decoder-step graph for incremental decode |
| `moss_audio_tokenizer_decode_shared.data` | External weights shared by the decoder graphs |
| `codec_browser_onnx_meta.json` | Metadata for browser / ONNX runtime integration |

## Quick Start

```bash
huggingface-cli download OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX \
    --local-dir weights/MOSS-Audio-Tokenizer-Nano-ONNX
```

This repository is typically used together with [OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX) for fully torch-free MOSS-TTS-Nano deployment.

## Main Repositories

| Repository | Description |
|------------|-------------|
| [OpenMOSS/MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS-Nano) | MOSS-TTS-Nano source code and inference pipeline |
| [OpenMOSS-Team/MOSS-TTS-Nano](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano) | PyTorch MOSS-TTS-Nano weights |
| [OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano) | PyTorch MOSS-Audio-Tokenizer-Nano weights |
| [OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX) | Companion ONNX TTS weights |

## About MOSS-Audio-Tokenizer-Nano

**MOSS-Audio-Tokenizer-Nano** serves as the lightweight codec backbone for MOSS-TTS-Nano. It keeps the same unified audio-token interface used across the MOSS-TTS family while reducing inference cost for CPU and browser deployment scenarios.

For the original PyTorch implementation, setup instructions, and more background, see:

- [MOSS-Audio-Tokenizer Repository](https://github.com/OpenMOSS/MOSS-Audio-Tokenizer)
- [MOSS-TTS-Nano Repository](https://github.com/OpenMOSS/MOSS-TTS-Nano)

## Citation

If you use the MOSS-TTS work in your research or product, please cite:

```bibtex
@misc{openmoss2026mossttsnano,
  title={MOSS-TTS-Nano},
  author={OpenMOSS Team},
  year={2026},
  howpublished={GitHub repository},
  url={https://github.com/OpenMOSS/MOSS-TTS-Nano}
}
```

```bibtex
@misc{gong2026mossttstechnicalreport,
  title={MOSS-TTS Technical Report},
  author={Yitian Gong and Botian Jiang and Yiwei Zhao and Yucheng Yuan and Kuangwei Chen and Yaozhou Jiang and Cheng Chang and Dong Hong and Mingshu Chen and Ruixiao Li and Yiyang Zhang and Yang Gao and Hanfu Chen and Ke Chen and Songlin Wang and Xiaogui Yang and Yuqian Zhang and Kexin Huang and ZhengYuan Lin and Kang Yu and Ziqi Chen and Jin Wang and Zhaoye Fei and Qinyuan Cheng and Shimin Li and Xipeng Qiu},
  year={2026},
  eprint={2603.18090},
  archivePrefix={arXiv},
  primaryClass={cs.SD},
  url={https://arxiv.org/abs/2603.18090}
}
```

```bibtex
@misc{gong2026mossaudiotokenizerscalingaudiotokenizers,
  title={MOSS-Audio-Tokenizer: Scaling Audio Tokenizers for Future Audio Foundation Models},
  author={Yitian Gong and Kuangwei Chen and Zhaoye Fei and Xiaogui Yang and Ke Chen and Yang Wang and Kexin Huang and Mingshu Chen and Ruixiao Li and Qingyuan Cheng and Shimin Li and Xipeng Qiu},
  year={2026},
  eprint={2602.10934},
  archivePrefix={arXiv},
  primaryClass={cs.SD},
  url={https://arxiv.org/abs/2602.10934}
}
```
