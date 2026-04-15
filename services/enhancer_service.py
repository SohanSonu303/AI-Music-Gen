"""
AI Style Enhancer Service
=========================
Preset-based audio enhancement: each genre preset applies a curated DSP chain.
Intensity controls the dry/wet blend — 0.0 = original unchanged, 1.0 = full preset.

Pipeline per preset:
  dry  = audio.copy()
  processed = pedalboard_chain(audio)  [→ stereo widen if preset uses it]
                                        [→ analog saturation for Vintage]
  output = dry*(1-intensity) + processed*intensity
  → crest-factor-aware loudness match
  → Limiter(-0.5 dBFS)

Presets
-------
  lofi      — Lo-Fi / Cassette    : warm, dusty, bedroom-cassette character
  edm       — EDM / Club          : punchy, wide, loud, commercial-ready
  cinematic — Cinematic / Score   : grand, spacious, concert-hall reverb
  pop       — Pop / Radio         : bright, polished, streaming-ready
  chill     — Chill / Ambient     : soft, dreamy, no harsh edges
  vintage   — Vintage / Classic   : warm tube saturation, 70s studio sound
"""

import logging

import numpy as np
from pedalboard import (
    Bitcrush,
    Chorus,
    Compressor,
    HighpassFilter,
    HighShelfFilter,
    Limiter,
    LowShelfFilter,
    Pedalboard,
    PeakFilter,
    Reverb,
)

from services.warmth_service import analog_saturate

logger = logging.getLogger(__name__)

_EPS = 1e-10


# ── Preset Registry ────────────────────────────────────────────────────────────
#
# Each preset entry:
#   name          : display name
#   description   : 1-line description shown in UI
#   tags          : list of genre/style tags
#   stereo_width  : 0.0 = no widening; >0 = apply stereo_widen() after chain
#   saturation    : None | (drive, asymmetry) — analog saturation for Vintage only
#   chain_def     : list of (PluginClass, kwargs_dict) — built fresh each call
#
# Chains are NOT instantiated at module load (avoids pickling issues with Celery).

PRESETS: dict = {
    "lofi": {
        "name":        "Lo-Fi",
        "description": "Warm, dusty cassette character — bedroom recordings and lo-fi hip hop",
        "tags":        ["hip-hop", "cassette", "bedroom", "vintage"],
        "stereo_width": 0.0,
        "saturation":  None,
        "chain_def": [
            (HighpassFilter,  {"cutoff_frequency_hz": 80.0}),
            (LowShelfFilter,  {"cutoff_frequency_hz": 200.0,  "gain_db":  2.0}),
            (HighShelfFilter, {"cutoff_frequency_hz": 8000.0, "gain_db": -4.0}),
            (Bitcrush,        {"bit_depth": 12.0}),
            (Chorus,          {"rate_hz": 0.8, "depth": 0.3, "centre_delay_ms": 7.0, "mix": 0.2}),
            # dry_level = 1 - wet_level so total energy stays constant (not additive)
            (Reverb,          {"room_size": 0.25, "damping": 0.7, "wet_level": 0.12, "dry_level": 0.88}),
            # Ratio reduced 3:1 → 2:1, slower attack — glue without squashing
            (Compressor,      {"threshold_db": -18.0, "ratio": 2.0, "attack_ms": 30.0, "release_ms": 150.0}),
        ],
    },

    "edm": {
        "name":        "EDM / Club",
        "description": "Punchy, wide and loud — commercial electronic and dance music",
        "tags":        ["electronic", "dance", "club", "edm"],
        # Width reduced 0.5 → 0.4: side channel was amplified 1.5× causing limiter pumping
        "stereo_width": 0.4,
        "saturation":  None,
        "chain_def": [
            (HighpassFilter,  {"cutoff_frequency_hz": 40.0}),
            (PeakFilter,      {"cutoff_frequency_hz": 60.0,    "gain_db":  3.0, "q": 1.5}),
            # Presence boost reduced 2 → 1 dB at wider Q to avoid metallic harshness
            (PeakFilter,      {"cutoff_frequency_hz": 3500.0,  "gain_db":  1.0, "q": 0.7}),
            (HighShelfFilter, {"cutoff_frequency_hz": 12000.0, "gain_db":  2.0}),
            # Ratio reduced 4:1 → 2.5:1, threshold raised -12 → -8 dB, slower attack
            # Removed in-chain Limiter — it caused double-limiter pumping with final safety limiter
            (Compressor,      {"threshold_db": -8.0, "ratio": 2.5, "attack_ms": 10.0, "release_ms": 80.0}),
            # Post-comp de-emphasis: tame harshness locked in by compression
            (PeakFilter,      {"cutoff_frequency_hz": 3500.0,  "gain_db": -1.0, "q": 1.5}),
        ],
    },

    "cinematic": {
        "name":        "Cinematic",
        "description": "Grand and spacious — film scores, orchestral and epic trailers",
        "tags":        ["film", "orchestral", "trailer", "score", "epic"],
        # Width reduced 0.6 → 0.4: 1.6× side amplification was pushing peaks into limiter
        "stereo_width": 0.4,
        "saturation":  None,
        "chain_def": [
            (HighpassFilter,  {"cutoff_frequency_hz": 30.0}),
            (LowShelfFilter,  {"cutoff_frequency_hz": 120.0,  "gain_db":  1.5}),
            (PeakFilter,      {"cutoff_frequency_hz": 800.0,  "gain_db": -1.0, "q": 0.8}),
            (HighShelfFilter, {"cutoff_frequency_hz": 10000.0,"gain_db":  1.0}),
            # dry_level = 1 - wet_level so total energy stays constant (not additive)
            (Reverb,          {"room_size": 0.7, "damping": 0.6, "wet_level": 0.25, "dry_level": 0.75}),
            (Compressor,      {"threshold_db": -20.0, "ratio": 2.0, "attack_ms": 40.0, "release_ms": 300.0}),
        ],
    },

    "pop": {
        "name":        "Pop / Radio",
        "description": "Bright, polished and streaming-ready — commercial pop and radio",
        "tags":        ["pop", "commercial", "streaming", "radio"],
        "stereo_width": 0.4,
        "saturation":  None,
        "chain_def": [
            (HighpassFilter,  {"cutoff_frequency_hz": 60.0}),
            (PeakFilter,      {"cutoff_frequency_hz": 200.0,  "gain_db": -1.5, "q": 0.8}),
            # Presence boost reduced 1.5 → 1.0 dB to avoid shrill compression artifact
            (PeakFilter,      {"cutoff_frequency_hz": 3000.0, "gain_db":  1.0, "q": 1.0}),
            (HighShelfFilter, {"cutoff_frequency_hz": 10000.0,"gain_db":  2.0}),
            # Ratio reduced 3:1 → 2:1, threshold raised -14 → -10 dB, slower attack
            # Removed in-chain Limiter — redundant with final safety limiter; caused pumping
            (Compressor,      {"threshold_db": -10.0, "ratio": 2.0, "attack_ms": 18.0, "release_ms": 120.0}),
            # Post-comp de-emphasis: tame brightness locked in by compression
            (PeakFilter,      {"cutoff_frequency_hz": 3000.0, "gain_db": -0.8, "q": 1.5}),
        ],
    },

    "chill": {
        "name":        "Chill / Ambient",
        "description": "Soft, dreamy and spacious — lo-fi study, ambient and sleep music",
        "tags":        ["ambient", "study", "sleep", "lofi", "chill"],
        "stereo_width": 0.0,
        "saturation":  None,
        "chain_def": [
            (HighpassFilter,  {"cutoff_frequency_hz": 60.0}),
            (LowShelfFilter,  {"cutoff_frequency_hz": 200.0,  "gain_db":  1.0}),
            (HighShelfFilter, {"cutoff_frequency_hz": 8000.0, "gain_db": -2.0}),
            (Chorus,          {"rate_hz": 0.3, "depth": 0.2, "centre_delay_ms": 10.0, "mix": 0.15}),
            # dry_level = 1 - wet_level so total energy stays constant (not additive)
            (Reverb,          {"room_size": 0.5, "damping": 0.5, "wet_level": 0.20, "dry_level": 0.80}),
            (Compressor,      {"threshold_db": -22.0, "ratio": 2.0, "attack_ms": 60.0, "release_ms": 400.0}),
        ],
    },

    "vintage": {
        "name":        "Vintage / Classic",
        "description": "Warm tube saturation and 70s studio sound — classic rock and soul",
        "tags":        ["70s", "80s", "classic", "soul", "rock", "tube"],
        "stereo_width": 0.0,
        "saturation":  (1.3, 0.08),   # (drive, asymmetry) — even harmonics, tube/tape warmth
        "chain_def": [
            (HighpassFilter,  {"cutoff_frequency_hz": 50.0}),
            (LowShelfFilter,  {"cutoff_frequency_hz": 150.0,  "gain_db":  2.0}),
            (PeakFilter,      {"cutoff_frequency_hz": 3500.0, "gain_db": -1.0, "q": 1.0}),
            (HighShelfFilter, {"cutoff_frequency_hz": 12000.0,"gain_db": -2.0}),
            # Ratio reduced 2.5:1 → 2:1 for gentler glue compression
            (Compressor,      {"threshold_db": -18.0, "ratio": 2.0, "attack_ms": 25.0, "release_ms": 200.0}),
            # dry_level = 1 - wet_level so total energy stays constant (not additive)
            (Reverb,          {"room_size": 0.3, "damping": 0.7, "wet_level": 0.10, "dry_level": 0.90}),
        ],
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def stereo_widen(audio: np.ndarray, width: float) -> np.ndarray:
    """
    Mid-side stereo widening.

    Parameters
    ----------
    audio : float32 (channels, samples) — must have >= 2 channels
    width : 0.0 = no change; 1.0 = fully widened

    Returns
    -------
    float32 array, same shape as input.
    Mono (1 channel) returned unchanged.
    """
    if audio.shape[0] < 2:
        return audio
    width = float(np.clip(width, 0.0, 1.0))
    mid  = (audio[0].astype(np.float64) + audio[1].astype(np.float64)) / 2.0
    side = (audio[0].astype(np.float64) - audio[1].astype(np.float64)) / 2.0 * (1.0 + width)
    L = mid + side
    R = mid - side
    # Safety: if widening pushed peaks above 0.95, scale down to prevent limiter pumping
    peak = float(np.max(np.abs(np.stack([L, R]))))
    if peak > 0.95:
        scale = 0.95 / peak
        L *= scale
        R *= scale
    return np.stack([L.astype(np.float32), R.astype(np.float32)])


def _build_chain(preset_id: str) -> Pedalboard:
    """Build a fresh Pedalboard from the preset's chain_def list."""
    chain_def = PRESETS[preset_id]["chain_def"]
    plugins = [cls(**kwargs) for cls, kwargs in chain_def]
    return Pedalboard(plugins)


def get_presets_list() -> list:
    """Return preset metadata for the GET /enhance/presets endpoint."""
    return [
        {
            "id":          pid,
            "name":        p["name"],
            "description": p["description"],
            "tags":        p["tags"],
        }
        for pid, p in PRESETS.items()
    ]


# ── Main Processor ─────────────────────────────────────────────────────────────

def apply_preset(
    audio: np.ndarray,
    sr: int,
    preset_id: str,
    intensity: float = 0.7,
) -> np.ndarray:
    """
    Apply a genre style preset to audio using dry/wet blending.

    Parameters
    ----------
    audio     : float32 (channels, samples)
    sr        : sample rate
    preset_id : one of the keys in PRESETS
    intensity : 0.0 = bypass (dry only), 1.0 = full preset (wet only)

    Returns
    -------
    float32 array — loudness-matched, limiter-safe
    """
    if preset_id not in PRESETS:
        raise ValueError(f"Unknown preset '{preset_id}'. Valid: {list(PRESETS)}")

    intensity = float(np.clip(intensity, 0.0, 1.0))
    preset    = PRESETS[preset_id]

    # ── Measure input loudness (for crest-factor-aware matching later) ────────
    _in64       = audio.astype(np.float64)
    input_rms   = float(np.sqrt(np.mean(_in64 ** 2))) + _EPS
    input_peak  = float(np.max(np.abs(_in64))) + _EPS
    input_crest = input_peak / input_rms

    # ── Keep dry copy ─────────────────────────────────────────────────────────
    dry = audio.copy()

    # ── Apply pedalboard chain ────────────────────────────────────────────────
    chain     = _build_chain(preset_id)
    processed = chain(audio, sr)

    # ── Stereo widening (EDM, Cinematic, Pop) ─────────────────────────────────
    sw = preset["stereo_width"]
    if sw > 0.0:
        processed = stereo_widen(processed, sw)

    # ── Analog saturation (Vintage only) ─────────────────────────────────────
    sat = preset["saturation"]
    if sat is not None:
        drive, asymmetry = sat
        processed = analog_saturate(processed, drive=drive, asymmetry=asymmetry)

    # ── Dry / wet blend ───────────────────────────────────────────────────────
    # Handle shape mismatch: if stereo widen changed channel count, trim dry
    if dry.shape != processed.shape:
        min_ch  = min(dry.shape[0], processed.shape[0])
        min_smp = min(dry.shape[1], processed.shape[1])
        dry       = dry[:min_ch, :min_smp]
        processed = processed[:min_ch, :min_smp]

    blended = (dry.astype(np.float64) * (1.0 - intensity)
               + processed.astype(np.float64) * intensity).astype(np.float32)

    logger.info(
        "enhance: preset=%s intensity=%.2f stereo_width=%.1f saturation=%s",
        preset_id, intensity, sw, sat,
    )

    # ── Crest-factor-aware loudness match ─────────────────────────────────────
    # Same logic as warmth_service Stage 7.
    # When the chain compresses dynamics, output_crest < input_crest even if RMS
    # is matched — compressed audio feels louder. Penalty pulls gain back.
    _out64       = blended.astype(np.float64)
    output_rms   = float(np.sqrt(np.mean(_out64 ** 2))) + _EPS
    output_peak  = float(np.max(np.abs(_out64))) + _EPS
    output_crest = output_peak / output_rms
    crest_penalty = float(np.clip((output_crest / input_crest) ** 0.5, 0.6, 1.0))
    gain_linear   = float(np.clip((input_rms / output_rms) * crest_penalty, 0.25, 4.0))
    blended = (_out64 * gain_linear).astype(np.float32)

    # ── Safety limiter ────────────────────────────────────────────────────────
    limiter = Pedalboard([Limiter(threshold_db=-0.5, release_ms=50.0)])
    return limiter(blended, sr).astype(np.float32)
