from __future__ import annotations

import audioop
import io
import json
import statistics
import wave


def analyze_wav_bytes(blob: bytes) -> dict:
    with wave.open(io.BytesIO(blob), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        rate = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if channels > 1:
        raw = audioop.tomono(raw, sampwidth, 0.5, 0.5)

    duration_s = max(nframes / float(rate), 1e-6)
    frame_ms = 50
    chunk = int(rate * (frame_ms / 1000.0))
    if chunk <= 0:
        chunk = rate

    energies = []
    zcrs = []
    for i in range(0, nframes, chunk):
        seg = raw[i * sampwidth : min((i + chunk), nframes) * sampwidth]
        if not seg:
            continue
        rms = audioop.rms(seg, sampwidth)
        energies.append(rms)

        # zero crossing rate (16-bit signed assumption when sampwidth==2)
        if sampwidth == 2:
            samples = audioop.tomono(seg, 2, 1, 0)  # no-op but keeps bytes
            vals = [int.from_bytes(samples[j : j + 2], "little", signed=True) for j in range(0, len(samples), 2)]
        else:
            vals = [b - 128 for b in seg]
        crossings = 0
        for a, b in zip(vals, vals[1:]):
            if (a >= 0 > b) or (a < 0 <= b):
                crossings += 1
        zcrs.append(crossings / max(len(vals), 1))

    mean_energy = statistics.fmean(energies) if energies else 0.0
    stdev_energy = statistics.pstdev(energies) if len(energies) > 1 else 0.0
    mean_zcr = statistics.fmean(zcrs) if zcrs else 0.0

    # heuristic stress index [0,100]
    energy_cv = (stdev_energy / mean_energy) if mean_energy > 0 else 0.0
    stress_idx = max(0.0, min(100.0, (mean_zcr * 900) + (energy_cv * 120)))
    confidence_idx = max(0.0, min(100.0, 100 - stress_idx * 0.8))

    return {
        "duration_s": round(duration_s, 2),
        "mean_energy": round(mean_energy, 2),
        "energy_variability": round(energy_cv, 4),
        "mean_zcr": round(mean_zcr, 4),
        "stress_index": round(stress_idx, 2),
        "confidence_index": round(confidence_idx, 2),
    }


def parse_audio_metrics(messages: list[dict]) -> dict:
    metrics = []
    for m in messages:
        if m.get("role") != "audio_analyst":
            continue
        try:
            metrics.append(json.loads(m.get("content", "{}")))
        except Exception:
            pass
    if not metrics:
        return {"stress_index": None, "confidence_index": None}

    avg_stress = sum(float(x.get("stress_index", 0)) for x in metrics) / len(metrics)
    avg_conf = sum(float(x.get("confidence_index", 0)) for x in metrics) / len(metrics)
    return {"stress_index": round(avg_stress, 2), "confidence_index": round(avg_conf, 2)}
