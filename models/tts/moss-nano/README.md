---
license: apache-2.0
library_name: onnx
pipeline_tag: text-to-speech
tags:
  - text-to-speech
  - audio
  - moss-tts-family
  - moss-tts-nano
  - onnx
  - onnxruntime
  - browser
  - cpu
---

# MOSS-TTS-Nano-100M-ONNX

This repository provides the **ONNX exports** of [MOSS-TTS-Nano](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano), a **0.1B multilingual tiny speech generation model** from [MOSI.AI](https://mosi.cn/#hero) and the [OpenMOSS team](https://www.open-moss.com/). It is designed for **torch-free**, lightweight deployment on CPU and in the browser, and is intended to be used together with [MOSS-Audio-Tokenizer-Nano-ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX).

## Overview

MOSS-TTS-Nano focuses on the part of TTS deployment that matters most in practice: **small footprint**, **low latency**, **good enough quality for realtime products**, and **simple local setup**. It uses a pure autoregressive **Audio Tokenizer + LLM** pipeline and keeps the inference workflow friendly for browser demos, local CPU runtimes, and other lightweight integrations.

Main characteristics:

- **Tiny model size**: about **0.1B parameters**
- **Native audio format**: **48 kHz**, **2-channel** output
- **Multilingual**: same language coverage as the PyTorch `MOSS-TTS-Nano` release
- **Pure autoregressive architecture**: built on **Audio Tokenizer + LLM**
- **Streaming-friendly export**: split into prefill / decode-step / local decoder ONNX graphs
- **CPU and browser deployment**: designed for `onnxruntime` and `onnxruntime-web`

This repository contains the exported ONNX graphs only. If you want the original PyTorch model card and plug-and-play local inference scripts, please use [OpenMOSS-Team/MOSS-TTS-Nano](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano) or the [OpenMOSS/MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS-Nano) source repository.

## Supported Backends

| Backend | Runtime | Use Case |
|---------|---------|----------|
| **ONNX Runtime (CPU)** | `onnxruntime` | Local CPU inference |
| **ONNX Runtime Web** | `onnxruntime-web` | Browser demos / extensions |

## Repository Contents

| File | Description |
|------|-------------|
| `moss_tts_prefill.onnx` | Global transformer prefill graph |
| `moss_tts_decode_step.onnx` | Global transformer decode-step graph with KV cache |
| `moss_tts_local_decoder.onnx` | Local decoder graph |
| `moss_tts_local_cached_step.onnx` | Local cached-step graph |
| `moss_tts_local_fixed_sampled_frame.onnx` | Local frame sampling graph |
| `moss_tts_global_shared.data` | External weights shared by the global graphs |
| `moss_tts_local_shared.data` | External weights shared by the local graphs |
| `tokenizer.model` | SentencePiece tokenizer used by the text frontend |
| `tts_browser_onnx_meta.json` | Metadata for ONNX runtime integration |
| `browser_poc_manifest.json` | Example manifest for browser-based integration |

## Quick Start

```bash
huggingface-cli download OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX \
    --local-dir weights/MOSS-TTS-Nano-100M-ONNX

huggingface-cli download OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX \
    --local-dir weights/MOSS-Audio-Tokenizer-Nano-ONNX
```

The TTS repo provides the language model and text tokenizer exports, while the companion codec repo provides waveform encode/decode ONNX models.

## Main Repositories

| Repository | Description |
|------------|-------------|
| [OpenMOSS/MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS-Nano) | MOSS-TTS-Nano source code, demos, and PyTorch inference |
| [OpenMOSS-Team/MOSS-TTS-Nano](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano) | PyTorch MOSS-TTS-Nano weights |
| [OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX) | Companion ONNX audio tokenizer |
| [OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano) | PyTorch audio tokenizer weights |
| [OpenMOSS/MOSS-TTS-Nano-Reader](https://github.com/OpenMOSS/MOSS-TTS-Nano-Reader) | Browser reading application built on top of the ONNX stack |

## About MOSS-TTS-Nano

MOSS-TTS-Nano is an open-source multilingual tiny speech generation model built for realtime speech generation and lightweight deployment. The ONNX export keeps the same core architecture as the PyTorch release while making it easier to integrate into browser and CPU-only runtimes without a PyTorch dependency.

For the full project introduction, demos, and PyTorch usage, see:

- [MOSS-TTS-Nano Repository](https://github.com/OpenMOSS/MOSS-TTS-Nano)
- [MOSS-TTS-Nano on Hugging Face](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano)

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
