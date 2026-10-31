> **Sample output.** This is a real `dictation-bench bench` report, unedited apart from this
> note, from an Apple M2 MacBook Air running two resident NeMo-Speech.cpp engines (Parakeet
> TDT 0.6B v3 and Nemotron streaming 0.6B) on the bundled synthetic corpus. It is here so you
> can see the shape of the output before installing anything. **Your numbers will differ** —
> that is the entire point of measuring on your own machine. Reproduce with:
>
> ```bash
> dictation-bench bench --preset nemo-speech-server --engine-json \
>   '{"name":"nemotron-streaming","type":"http","url":"http://127.0.0.1:8097/v1/audio/transcriptions","capabilities":{"service":true,"offline":true,"streaming_encoder":true}}'
> ```

# Local dictation: which engine for this machine?

Measured 2026-10-31 14:48 PDT on **Apple M2**, 25.8 GB RAM, macOS-26.7.1-arm64-arm-64bit.

Corpus: 28 clips (112.8 s of audio): 19 main, 6 numeric, 1 long, 2 stress.

## The table

| Engine | Everyday WER | Numbers | First phrase | After that | Resident? |
|:--------------------:|:----------:|:------:|:----------:|:---------:|:-------:|
| nemo-speech-server | 1.9% | 17.2% | 143 ms | 96 ms | yes |
| nemotron-streaming | 3.8% | 0.0% | 117 ms | 115 ms | yes |

_First phrase = you pressed the key with the model not loaded yet (what a freshly launched app costs you). After that = every following phrase. (—) means the number could not be measured._

## Accuracy in detail

| Group | nemo-speech-server | nemotron-streaming |
|:---|:--:|:--:|
| Everyday prose | 2.6% | 4.6% |
| Numbers | 17.2% | 0.0% |
| Long utterance | 0.0% | 1.6% |
| Acronyms | 17.2% | 10.3% |

**Everyday dictation, with the raw error counts:**

| Engine | Word errors | Reference words | WER (95% range) |
|:---|---:|---:|:--:|
| nemo-speech-server | 5 | 260 | 1.9% (0.8–4.4%) |
| nemotron-streaming | 10 | 260 | 3.8% (2.1–6.9%) |

nemo-speech-server is ahead of nemotron-streaming by 5 word errors out of 260. The difference comes from: `n02` (7→0 errors), `n01` (4→0 errors), `m06` (0→2 errors), `s01` (2→0 errors).

## Why published WER numbers disagree

| Engine | Naive scorer | Whisper-style scorer | Number-aware scorer |
|:--|--:|--:|--:|
| nemo-speech-server | 5.9% | 5.9% | 5.9% |
| nemotron-streaming | 3.7% | 3.7% | 3.7% |

## Pros and cons

### nemo-speech-server

- ✅ Most accurate everyday dictation on this machine (1.9% WER)
- ✅ Fastest after the first phrase (96 ms)
- ✅ Resident (no reload per phrase)
- ✅ Offline (no network)
- ⚠️ No words while you speak
- ⚠️ Misreads numbers (17.2% on the numbers group)
- ℹ️ Start with: nemo-speech serve --asr-model parakeet-tdt --host 127.0.0.1 --port 50060 --no-ui

### nemotron-streaming

- ✅ Resident (no reload per phrase)
- ✅ Offline (no network)
- ✅ Writes numbers correctly here (0.0% on the numbers group, vs 4.6% on prose)
- ⚠️ Least accurate everyday dictation here (3.8% WER)
- ⚠️ A streaming encoder exists upstream, but this benchmark drove it through the batch endpoint, so no live-partial latency was measured

## What I would pick

- **Accuracy matters most:** **nemo-speech-server** (1.9% WER).
- **You launch it once and dictate all day:** **nemotron-streaming** — its first phrase after launch is the quickest (117 ms).
- **Nothing here shows words while you speak.** If that is what you are used to, these are all push-to-talk style: you get the text when you stop.

## What this does not tell you

- **Your voice and your microphone are not the test.** Default synthetic
  speakers are cleaner than a real room; real accuracy gaps tend to be larger.
  Use `dictation-bench corpus --from-clip recording.wav --ref "what you said"`.
- **Latency here is engine time, not the full felt wait.** Launching an app,
  audio capture, the paste keystroke and clipboard handling add tens to
  hundreds of milliseconds that no engine-level benchmark can see.
- **One run, one machine.** Re-run it if you care; that is the point.
