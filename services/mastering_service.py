"""
AI Platform Mastering Service
==============================
Analyses a track's current loudness and applies a platform-specific mastering
chain to hit industry-standard LUFS targets.

Pipeline per platform:
  1. apply_mastering_eq       — platform-specific tonal shaping
  2. stereo_widen             — subtle stereo imaging (music only, width=0.1)
  3. apply_glue_compression   — gentle glue compression
  4. measure_lufs             — measure integrated LUFS post-compression
  5. apply_lufs_gain          — linear gain to reach target LUFS
  6. apply_true_peak_limiter  — true-peak ceiling per platform spec
  7. report generation        — before/after LUFS, true peak, changes list

Platforms
---------
  spotify    — -14 LUFS / -1 dBTP
  youtube    — -13 LUFS / -1 dBTP
  tiktok     — -14 LUFS / -2 dBTP  (extra headroom for codec re-encoding)
  podcast    — -16 LUFS / -1 dBTP
  apple      — -16 LUFS / -1 dBTP
  soundcloud — -14 LUFS / -1 dBTP

NOTE: pyloudnorm expects (samples, channels) — codebase uses (channels, samples).
      All calls to pyloudnorm.Meter use audio.T to transpose.
"""

import logging

import numpy as np
import pyloudnorm as pyln
from pedalboard import (
    Compressor,
    HighpassFilter,
    HighShelfFilter,
    Limiter,
    LowShelfFilter,
    PeakFilter,
    Pedalboard,
)

from services.enhancer_service import stereo_widen

logger = logging.getLogger(__name__)

_EPS = 1e-10

# ── Platform Profiles ──────────────────────────────────────────────────────────

PLATFORM_PROFILES: dict[str, dict] = {
    "spotify": {
        "name": "Spotify",
        "target_lufs": -14.0,
        "true_peak_db": -1.0,
        "description": "Streaming — loudness normalization to -14 LUFS",
        "icon": "🎵",
    },
    "youtube": {
        "name": "YouTube",
        "target_lufs": -13.0,
        "true_peak_db": -1.0,
        "description": "Video platform — slightly louder at -13 LUFS",
        "icon": "▶",
    },
    "tiktok": {
        "name": "TikTok / Reels",
        "target_lufs": -14.0,
        "true_peak_db": -2.0,
        "description": "Short-form video — extra headroom for codec re-encoding",
        "icon": "📱",
    },
    "podcast": {
        "name": "Podcast",
        "target_lufs": -16.0,
        "true_peak_db": -1.0,
        "description": "Speech content — quieter target per podcasting standard",
        "icon": "🎙",
    },
    "apple": {
        "name": "Apple Music",
        "target_lufs": -16.0,
        "true_peak_db": -1.0,
        "description": "Apple streaming — matches Apple Sound Check spec",
        "icon": "🍎",
    },
    "soundcloud": {
        "name": "SoundCloud",
        "target_lufs": -14.0,
        "true_peak_db": -1.0,
        "description": "Independent streaming — matches Spotify loudness",
        "icon": "☁",
    },
}


# ── LUFS & Peak Measurement ────────────────────────────────────────────────────

def measure_lufs(audio: np.ndarray, sr: int) -> float:
    """
    Measure integrated loudness (LUFS) per ITU-R BS.1770-4.

    pyloudnorm expects (samples, channels) — transpose from (channels, samples).
    Returns a negative float (e.g. -18.3) or a very negative value for near-silent audio.
    """
    audio_T = audio.T.astype(np.float64)
    meter = pyln.Meter(sr)  # K-weighting, 400ms block, BS.1770-4
    lufs = meter.integrated_loudness(audio_T)
    # pyloudnorm returns -inf for silence — replace with -120.0 sentinel
    if lufs != lufs or lufs < -120.0:  # NaN or -inf
        return -120.0
    return float(lufs)


def measure_true_peak_db(audio: np.ndarray) -> float:
    """Measure sample-peak in dBFS. Returns -120.0 for silent audio."""
    peak = float(np.max(np.abs(audio)))
    if peak < _EPS:
        return -120.0
    return float(20.0 * np.log10(peak))


# ── DSP Stages ─────────────────────────────────────────────────────────────────

def apply_mastering_eq(audio: np.ndarray, sr: int, platform: str) -> np.ndarray:
    """
    Apply platform-specific tonal correction.

    Music platforms (spotify / youtube / tiktok / apple / soundcloud):
      HPF 30Hz  — remove DC/subsonic rumble
      LowShelf +1dB @ 80Hz   — sub warmth
      PeakFilter -1dB @ 200Hz — tighten low-mid mud
      HighShelf +1dB @ 12kHz  — air and openness

    Podcast:
      HPF 80Hz              — hard-cut mic rumble
      PeakFilter -2dB @ 200Hz — remove boominess
      PeakFilter +1.5dB @ 3kHz — presence / intelligibility
      HighShelf -1dB @ 10kHz  — soften harsh mic top-end
    """
    if platform == "podcast":
        chain = Pedalboard([
            HighpassFilter(cutoff_frequency_hz=80.0),
            PeakFilter(cutoff_frequency_hz=200.0, gain_db=-2.0, q=0.9),
            PeakFilter(cutoff_frequency_hz=3000.0, gain_db=1.5, q=1.2),
            HighShelfFilter(cutoff_frequency_hz=10000.0, gain_db=-1.0),
        ])
    else:
        chain = Pedalboard([
            HighpassFilter(cutoff_frequency_hz=30.0),
            LowShelfFilter(cutoff_frequency_hz=80.0, gain_db=1.0),
            PeakFilter(cutoff_frequency_hz=200.0, gain_db=-1.0, q=0.9),
            HighShelfFilter(cutoff_frequency_hz=12000.0, gain_db=1.0),
        ])
    return chain(audio, sr)


def apply_glue_compression(audio: np.ndarray, sr: int, platform: str) -> np.ndarray:
    """
    Apply gentle glue compression to add cohesion without squashing dynamics.

    Music: 2:1 ratio, slow 40ms attack to let transients through
    Podcast: 3:1 ratio, faster 10ms attack for voice levelling
    """
    if platform == "podcast":
        chain = Pedalboard([
            Compressor(threshold_db=-18.0, ratio=3.0, attack_ms=10.0, release_ms=100.0),
        ])
    else:
        chain = Pedalboard([
            Compressor(threshold_db=-18.0, ratio=2.0, attack_ms=40.0, release_ms=200.0),
        ])
    return chain(audio, sr)


def apply_lufs_gain(
    audio: np.ndarray,
    target_lufs: float,
    current_lufs: float,
) -> tuple[np.ndarray, float]:
    """
    Apply linear gain to reach target LUFS.

    Gain is clamped to ±20dB to protect against insane boosts on near-silent files.
    Returns (gained_audio, gain_db_applied).
    """
    gain_db = float(np.clip(target_lufs - current_lufs, -20.0, 20.0))
    gain_linear = float(10.0 ** (gain_db / 20.0))
    return (audio * gain_linear).astype(np.float32), gain_db


def apply_true_peak_limiter(audio: np.ndarray, sr: int, ceiling_db: float) -> np.ndarray:
    """Apply a sample-accurate true-peak limiter at the specified ceiling (dBFS)."""
    chain = Pedalboard([Limiter(threshold_db=ceiling_db, release_ms=50.0)])
    return chain(audio, sr)


# ── Main Pipeline ──────────────────────────────────────────────────────────────

def master_for_platform(
    audio: np.ndarray,
    sr: int,
    platform: str,
) -> tuple[np.ndarray, dict]:
    """
    Apply a full mastering chain targeting the specified platform's loudness spec.

    Parameters
    ----------
    audio    : float32 ndarray (channels, samples)
    sr       : sample rate
    platform : one of the keys in PLATFORM_PROFILES

    Returns
    -------
    (mastered_audio, report_dict)

    report_dict shape:
    {
      platform, target_lufs, true_peak_ceiling,
      before: { lufs, true_peak_db },
      after:  { lufs, true_peak_db },
      gain_applied_db,
      changes: [str, ...]
    }
    """
    if platform not in PLATFORM_PROFILES:
        raise ValueError(
            f"Unknown platform '{platform}'. Valid: {list(PLATFORM_PROFILES)}"
        )

    profile = PLATFORM_PROFILES[platform]
    target_lufs = profile["target_lufs"]
    true_peak_ceiling = profile["true_peak_db"]
    changes: list[str] = []

    # ── Before measurements ───────────────────────────────────────────────────
    before_lufs = measure_lufs(audio, sr)
    before_peak = measure_true_peak_db(audio)

    # Guard: near-silent file — skip gain, return warning
    if before_lufs <= -70.0:
        logger.warning(
            "master_for_platform: near-silent audio (LUFS=%.1f), skipping", before_lufs
        )
        return audio.copy(), {
            "platform": profile["name"],
            "target_lufs": target_lufs,
            "true_peak_ceiling": true_peak_ceiling,
            "before": {"lufs": before_lufs, "true_peak_db": round(before_peak, 1)},
            "after":  {"lufs": before_lufs, "true_peak_db": round(before_peak, 1)},
            "gain_applied_db": 0.0,
            "changes": ["⚠ Near-silent audio detected — no processing applied"],
        }

    # ── Stage 1: Platform EQ ──────────────────────────────────────────────────
    processed = apply_mastering_eq(audio, sr, platform)
    if platform == "podcast":
        changes.append("Podcast voice EQ: HPF 80Hz, −2dB@200Hz mud, +1.5dB@3kHz presence, −1dB@10kHz shelf")
    else:
        changes.append("Music EQ: HPF 30Hz, +1dB@80Hz sub, −1dB@200Hz mud, +1dB@12kHz air shelf")

    # ── Stage 2: Stereo widening (music only, subtle) ─────────────────────────
    if platform != "podcast" and audio.shape[0] == 2:
        processed = stereo_widen(processed, width=0.1)
        changes.append("Stereo imaging: +10% width (subtle)")

    # ── Stage 3: Glue compression ─────────────────────────────────────────────
    processed = apply_glue_compression(processed, sr, platform)
    if platform == "podcast":
        changes.append("Voice compression: 3:1 ratio, 10ms attack, 100ms release")
    else:
        changes.append("Glue compression: 2:1 ratio, 40ms attack, 200ms release")

    # ── Stage 4: Measure post-compression LUFS ───────────────────────────────
    post_comp_lufs = measure_lufs(processed, sr)

    # ── Stage 5: LUFS gain to hit target ─────────────────────────────────────
    processed, gain_db = apply_lufs_gain(processed, target_lufs, post_comp_lufs)
    sign = "+" if gain_db >= 0 else ""
    changes.append(
        f"LUFS gain: {sign}{gain_db:.1f} dB  ({post_comp_lufs:.1f} → {target_lufs:.1f} LUFS)"
    )

    # ── Stage 6: True-peak limiter ────────────────────────────────────────────
    processed = apply_true_peak_limiter(processed, sr, true_peak_ceiling)
    changes.append(f"True-peak limiter: ceiling {true_peak_ceiling:.1f} dBFS")

    # ── After measurements ────────────────────────────────────────────────────
    after_lufs = measure_lufs(processed, sr)
    after_peak = measure_true_peak_db(processed)

    logger.info(
        "master_for_platform: platform=%s  before=%.1fLUFS/%.1fdBTP  "
        "after=%.1fLUFS/%.1fdBTP  gain=%.1fdB",
        platform, before_lufs, before_peak, after_lufs, after_peak, gain_db,
    )

    report = {
        "platform": profile["name"],
        "target_lufs": target_lufs,
        "true_peak_ceiling": true_peak_ceiling,
        "before": {
            "lufs": round(before_lufs, 1),
            "true_peak_db": round(before_peak, 1),
        },
        "after": {
            "lufs": round(after_lufs, 1),
            "true_peak_db": round(after_peak, 1),
        },
        "gain_applied_db": round(gain_db, 1),
        "changes": changes,
    }

    return processed.astype(np.float32), report
