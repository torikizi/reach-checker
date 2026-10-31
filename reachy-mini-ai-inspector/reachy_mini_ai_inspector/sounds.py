"""Short, quiet verdict cues generated locally; no sound files or downloads."""
import numpy as np


NOTES = {
    "OK": ((880, .11), (1320, .16)),
    "NG": ((440, .14), (330, .20)),
    "REVIEW": ((660, .10), (660, .10), (660, .10)),
}


def verdict_samples(verdict, sample_rate):
    if verdict not in NOTES:
        raise ValueError("判定音はOK / NG / REVIEWのみです")
    if not 8000 <= sample_rate <= 192000:
        raise ValueError("本体スピーカーのサンプルレートを取得できません")
    parts = [np.zeros(round(sample_rate * .04), dtype=np.float32)]
    for frequency, duration in NOTES[verdict]:
        n = round(sample_rate * duration)
        phase = np.arange(n, dtype=np.float32) * (2 * np.pi * frequency / sample_rate)
        tone = .16 * (np.sin(phase) + .20 * np.sin(3 * phase))
        attack, release = round(sample_rate * .008), round(sample_rate * .025)
        tone[:attack] *= np.linspace(0, 1, attack, dtype=np.float32)
        tone[-release:] *= np.linspace(1, 0, release, dtype=np.float32)
        parts.extend((tone.astype(np.float32), np.zeros(round(sample_rate * .055), dtype=np.float32)))
    return np.concatenate(parts)
