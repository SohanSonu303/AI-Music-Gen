"""
AI Analog Warmth Service
========================
Adaptive 7-stage DSP pipeline that fixes AI-music "metallic sheen" and adds
analog warmth character. All processing is local — no LLM or API calls.

Normal mode pipeline:
  Input float32
    → [Pedalboard chain 1]  Stage 1: Subsonic cleanup (HPF 30Hz)
                            Stage 2: Adaptive de-harshness (PeakFilter x2 + HighShelf)
                            Stage 3: Body enhancement (LowShelf + PeakFilter)
    → [numpy]               Stage 4: Analog saturation (asymmetric tanh → even harmonics)
    → [Pedalboard chain 2]  Stage 5: Moog-style LPF (LadderFilter LPF24)
                            Stage 6: Glue compression (Compressor)
    → [numpy]               Stage 7: Loudness match (RMS correction)
    → [Pedalboard]          Safety limiter (Limiter -0.5 dBFS)
    → Output float32

vocal_mode=True changes:
  Stage 2: de-harshness shifts to sibilance zone (5.5kHz + 8.5kHz) with stronger cuts
  Stage 3: body moves to chest resonance (300Hz) + vocal presence (3kHz)
  Stage 4: lighter saturation (drive capped at 1.5 — avoids distorting vocals)
  Stage 5: higher LPF cutoff (16–18kHz) — preserves vocal air and breath
  Stage 5.5 (vocal only): short room Reverb — removes the "in a computer" dryness
  Stage 6: faster attack + lower ratio — natural breath variation instead of squashing
"""

import logging
from typing import Optional

import numpy as np
from pedalboard import (
    Compressor,
    HighpassFilter,
    HighShelfFilter,
    LadderFilter,
    Limiter,
    LowShelfFilter,
    PeakFilter,
    Pedalboard,
    Reverb,
)

logger = logging.getLogger(__name__)

_EPS = 1e-10  # guard against log(0) / div-by-zero


# ── Spectral Analysis ──────────────────────────────────────────────────────────

def analyze_spectrum(audio: np.ndarray, sr: int) -> dict:
    """
    Compute a spectral profile of the audio using windowed FFT.

    Parameters
    ----------
    audio : np.ndarray  shape (channels, samples), float32
    sr    : int         sample rate

    Returns
    -------
    dict with keys:
      spectral_profile  — 6-band energy percentages (sum ≈ 100)
      diagnostics       — derived metrics that drive the DSP stages
    """
    # Mix to mono for analysis
    mono = audio.mean(axis=0).astype(np.float64)  # (samples,)

    if len(mono) == 0:
        return _empty_analysis()

    window_size = 8192
    hop_size = window_size // 2
    window = np.hanning(window_size)

    # Accumulate magnitude spectrum across all windows
    n_bins = window_size // 2 + 1
    mag_acc = np.zeros(n_bins, dtype=np.float64)
    n_windows = 0

    for start in range(0, len(mono) - window_size + 1, hop_size):
        frame = mono[start:start + window_size] * window
        mag_acc += np.abs(np.fft.rfft(frame))
        n_windows += 1

    if n_windows == 0:
        # Audio shorter than one window — use the whole clip zero-padded
        frame = np.zeros(window_size)
        frame[:len(mono)] = mono * window[:len(mono)]
        mag_acc = np.abs(np.fft.rfft(frame))
        n_windows = 1

    mag = mag_acc / n_windows
    freqs = np.fft.rfftfreq(window_size, d=1.0 / sr)

    # ── Band energies ──────────────────────────────────────────────────────────
    def _band(f_lo, f_hi) -> float:
        mask = (freqs >= f_lo) & (freqs < f_hi)
        return float(np.mean(mag[mask])) + _EPS if mask.any() else _EPS

    sub      = _band(20,    60)
    bass     = _band(60,    250)
    low_mid  = _band(250,   2000)
    high_mid = _band(2000,  6000)
    presence = _band(6000,  12000)
    air      = _band(12000, 20000)
    total    = sub + bass + low_mid + high_mid + presence + air

    # ── Derived metrics ────────────────────────────────────────────────────────

    # harshness_ratio: >1 means top-heavy (harsh), <1 means warm
    harshness_ratio = (high_mid + presence) / (low_mid + bass + _EPS)

    # spectral_tilt: slope of log-energy vs log-freq across the 6 bands
    # Negative = warm/dark (normal), less-negative/positive = bright/harsh (AI sheen)
    band_log_freqs   = np.log([40, 150, 1000, 4000, 9000, 16000])
    band_log_energies = np.log([sub, bass, low_mid, high_mid, presence, air])
    spectral_tilt = float(np.polyfit(band_log_freqs, band_log_energies, 1)[0])

    # crest_factor: peak/RMS in dB — high = dynamic, low = compressed
    rms = float(np.sqrt(np.mean(mono ** 2))) + _EPS
    peak = float(np.max(np.abs(mono))) + _EPS
    crest_factor_db = float(20 * np.log10(peak / rms))

    # mid_scoop_ratio: low value = hollow midrange (masking / thin)
    mid_scoop_ratio = low_mid / (bass + high_mid + _EPS)

    # overall_rms_db: drives compression threshold
    overall_rms_db = float(20 * np.log10(rms))

    return {
        "spectral_profile": {
            "sub":      round(sub      / total * 100, 2),
            "bass":     round(bass     / total * 100, 2),
            "low_mid":  round(low_mid  / total * 100, 2),
            "high_mid": round(high_mid / total * 100, 2),
            "presence": round(presence / total * 100, 2),
            "air":      round(air      / total * 100, 2),
        },
        "diagnostics": {
            "harshness_ratio":  round(harshness_ratio,  3),
            "spectral_tilt":    round(spectral_tilt,    3),
            "crest_factor_db":  round(crest_factor_db,  2),
            "mid_scoop_ratio":  round(mid_scoop_ratio,  3),
            "overall_rms_db":   round(overall_rms_db,   2),
        },
    }


def _empty_analysis() -> dict:
    return {
        "spectral_profile": {"sub": 0, "bass": 0, "low_mid": 0, "high_mid": 0, "presence": 0, "air": 0},
        "diagnostics": {
            "harshness_ratio": 1.0, "spectral_tilt": 0.0,
            "crest_factor_db": 12.0, "mid_scoop_ratio": 0.5, "overall_rms_db": -18.0,
        },
    }


# ── Adaptive Parameter Engine ─────────────────────────────────────────────────

def compute_warmth_params(analysis: dict, intensity: float, vocal_mode: bool = False) -> dict:
    """
    Map spectral analysis metrics → adaptive DSP parameters, all scaled by intensity.

    Parameters
    ----------
    analysis   : dict from analyze_spectrum()
    intensity  : float 0.0–1.0
    vocal_mode : bool — when True, overrides frequencies and params for vocal content

    Returns
    -------
    dict of concrete DSP parameter values for all pipeline stages, including
    EQ frequencies so the chain is not hardcoded.
    """
    intensity = float(np.clip(intensity, 0.0, 1.0))
    diag = analysis["diagnostics"]
    profile = analysis["spectral_profile"]

    harshness_ratio  = diag["harshness_ratio"]
    spectral_tilt    = diag["spectral_tilt"]
    crest_factor_db  = diag["crest_factor_db"]
    mid_scoop_ratio  = diag["mid_scoop_ratio"]
    overall_rms_db   = diag["overall_rms_db"]
    bass_pct         = profile["bass"]

    # ── Stage 2: De-harshness ─────────────────────────────────────────────────
    harsh_scale = float(np.clip((harshness_ratio - 0.5) / 1.5, 0.0, 1.0))
    tilt_scale  = float(np.clip((spectral_tilt + 2.0) / 4.0, 0.0, 1.0))

    if vocal_mode:
        # Vocals: target sibilance zone (consonant harshness + sibilance peak)
        deharsh_freq1  = 5500.0
        deharsh_freq2  = 8500.0
        deharsh_db1    = -(2.0 + 4.0 * harsh_scale) * intensity   # -2 to -6 dB
        deharsh_db2    = -(1.5 + 3.5 * harsh_scale) * intensity   # -1.5 to -5 dB
        high_shelf_db  = -(0.2 + 0.8 * tilt_scale)  * intensity   # light rolloff — keep vocal air
    else:
        # Full mix: target metallic sheen zone
        deharsh_freq1  = 3500.0
        deharsh_freq2  = 7000.0
        deharsh_db1    = -(1.0 + 3.0 * harsh_scale) * intensity   # -1 to -4 dB
        deharsh_db2    = -(0.5 + 2.5 * harsh_scale) * intensity   # -0.5 to -3 dB
        high_shelf_db  = -(0.5 + 2.0 * tilt_scale)  * intensity   # -0.5 to -2.5 dB

    # ── Stage 3: Body enhancement ─────────────────────────────────────────────
    body_scale  = float(np.clip(1.0 - bass_pct / 30.0, 0.0, 1.0))
    scoop_scale = float(np.clip(1.0 - mid_scoop_ratio / 0.4, 0.0, 1.0))

    if vocal_mode:
        # Vocals: chest resonance (300Hz) + presence (3kHz)
        bass_boost_freq = 300.0
        body_boost_freq = 3000.0
        bass_boost_db   = (0.5 + 1.0 * body_scale)  * intensity   # lighter chest boost
        body_boost_db   = (1.0 + 1.0 * intensity)                 # presence always boosted
    else:
        # Full mix: warmth (200Hz) + body (800Hz)
        bass_boost_freq = 200.0
        body_boost_freq = 800.0
        bass_boost_db   = (0.5 + 1.5 * body_scale)  * intensity   # +0.5 to +2 dB
        body_boost_db   = (0.5 + 1.0 * scoop_scale) * intensity   # +0.5 to +1.5 dB

    # ── Stage 4: Analog saturation ────────────────────────────────────────────
    drive_scale = float(np.clip((crest_factor_db - 6.0) / 14.0, 0.0, 1.0))

    if vocal_mode:
        # Lighter saturation — heavy drive distorts vocal formants
        saturation_drive     = 1.1 + 0.4 * drive_scale * intensity   # 1.1 to 1.5
        saturation_asymmetry = 0.03 + 0.05 * intensity               # 0.03 to 0.08
    else:
        saturation_drive     = 1.1 + 0.3 * drive_scale * intensity   # 1.1 to 1.4 (capped — avoids audible crunch)
        saturation_asymmetry = 0.05 + 0.03 * intensity               # 0.05 to 0.08 (capped — warmth not distortion)

    # ── Stage 5: Moog LPF ─────────────────────────────────────────────────────
    if vocal_mode:
        # Higher cutoff — preserve breath and vocal air above 16kHz
        ladder_cutoff    = 18000.0 - 2000.0 * intensity   # 18kHz → 16kHz
    else:
        ladder_cutoff    = 18000.0 - 4000.0 * intensity   # 18kHz → 14kHz
    ladder_resonance = 0.05 * intensity
    ladder_drive     = 1.0 + 0.3 * intensity

    # ── Stage 5.5: Room reverb (vocal mode only) ──────────────────────────────
    # Removes the "in a computer" dryness — even 8% wet makes vocals feel recorded
    reverb_room_size = 0.15 + 0.15 * intensity   # 0.15 → 0.30 (small room)
    reverb_wet_level = 0.05 + 0.08 * intensity   # 0.05 → 0.13 (subtle)
    reverb_damping   = 0.8                        # damp reverb tail (not bright/washy)

    # ── Stage 6: Glue / vocal compression ────────────────────────────────────
    comp_threshold = float(np.clip(overall_rms_db - 5.0, -28.0, -12.0))

    if vocal_mode:
        # Gentle vocal dynamics — preserves natural breath variation
        comp_ratio      = 1.1 + 0.6 * intensity    # 1.1:1 → 1.7:1 (was 1.5→2.5, too heavy)
        comp_attack_ms  = 15.0 - 10.0 * intensity  # 15ms → 5ms
        comp_release_ms = 100.0 - 50.0 * intensity # 100ms → 50ms
    else:
        # Light glue compression — not mastering compression
        comp_ratio      = 1.2 + 0.8 * intensity    # 1.2:1 → 2.0:1 (was 2:1→4:1, way too heavy)
        comp_attack_ms  = 40.0 - 20.0 * intensity  # 40ms → 20ms (slower = less pumping)
        comp_release_ms = 250.0 - 150.0 * intensity # 250ms → 100ms

    return {
        # Stage 2 — frequencies + gains
        "deharsh_freq1":       deharsh_freq1,
        "deharsh_freq2":       deharsh_freq2,
        "deharsh_db1":         round(deharsh_db1,         2),
        "deharsh_db2":         round(deharsh_db2,         2),
        "high_shelf_db":       round(high_shelf_db,       2),
        # Stage 3 — frequencies + gains
        "bass_boost_freq":     bass_boost_freq,
        "body_boost_freq":     body_boost_freq,
        "bass_boost_db":       round(bass_boost_db,       2),
        "body_boost_db":       round(body_boost_db,       2),
        # Stage 4
        "saturation_drive":    round(saturation_drive,    3),
        "saturation_asymmetry":round(saturation_asymmetry, 3),
        # Stage 5
        "ladder_cutoff":       round(ladder_cutoff,       1),
        "ladder_resonance":    round(ladder_resonance,    3),
        "ladder_drive":        round(ladder_drive,        3),
        # Stage 5.5 (vocal mode only — always stored, conditionally used)
        "reverb_room_size":    round(reverb_room_size,    3),
        "reverb_wet_level":    round(reverb_wet_level,    3),
        "reverb_damping":      reverb_damping,
        # Stage 6
        "comp_threshold":      round(comp_threshold,      1),
        "comp_ratio":          round(comp_ratio,          2),
        "comp_attack_ms":      round(comp_attack_ms,      1),
        "comp_release_ms":     round(comp_release_ms,     1),
    }


# ── Analog Saturation (numpy) ─────────────────────────────────────────────────

def analog_saturate(audio: np.ndarray, drive: float, asymmetry: float) -> np.ndarray:
    """
    Asymmetric tanh soft saturation that generates even-order harmonics (2nd, 4th).

    Even harmonics are what tubes, transformers, and tape produce — they are
    perceived as warmth. Pedalboard's Clipping/Distortion generate odd harmonics
    which sound harsh. This numpy implementation is the only way to do it correctly.

    Parameters
    ----------
    audio     : float32 array (channels, samples)
    drive     : 1.0–2.5 — controls harmonic intensity (higher = more saturation)
    asymmetry : 0.0–0.15 — controls even-harmonic content (tube/tape character)
    """
    x = audio.astype(np.float64) * drive
    # Asymmetry: x² term generates even harmonics
    x = x + asymmetry * (x ** 2)
    result = np.tanh(x)
    # Remove DC offset introduced by the asymmetric waveshaping
    result -= np.mean(result, axis=-1, keepdims=True)
    return result.astype(np.float32)


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def apply_warmth(audio: np.ndarray, sr: int, intensity: float = 0.5, vocal_mode: bool = False) -> np.ndarray:
    """
    Apply the full AI Analog Warmth pipeline to an audio array.

    Parameters
    ----------
    audio      : np.ndarray  float32 (channels, samples)
    sr         : int         sample rate
    intensity  : float       0.0 (subtle) → 1.0 (heavy analog character)
    vocal_mode : bool        when True, uses vocal-optimised EQ + adds room reverb

    Returns
    -------
    np.ndarray  float32 (channels, samples) — loudness-matched, limiter-safe
    """
    intensity = float(np.clip(intensity, 0.0, 1.0))

    # Measure input loudness for crest-factor-aware matching at the end
    _audio64   = audio.astype(np.float64)
    input_rms  = float(np.sqrt(np.mean(_audio64 ** 2))) + _EPS
    input_peak = float(np.max(np.abs(_audio64))) + _EPS
    input_crest = input_peak / input_rms   # dimensionless ratio; high = dynamic

    # ── Stage 0: Spectral analysis ────────────────────────────────────────────
    analysis = analyze_spectrum(audio, sr)
    params   = compute_warmth_params(analysis, intensity, vocal_mode=vocal_mode)

    logger.info(
        "warmth: intensity=%.2f vocal=%s harshness=%.2f tilt=%.2f rms=%.1fdB | "
        "deharsh=[%.0fHz %.1fdB, %.0fHz %.1fdB] shelf=%.1f "
        "bass=+%.1f@%.0fHz body=+%.1f@%.0fHz drive=%.2f ladder=%.0fHz comp=[%.1fdB %.1f:1]%s",
        intensity,
        vocal_mode,
        analysis["diagnostics"]["harshness_ratio"],
        analysis["diagnostics"]["spectral_tilt"],
        analysis["diagnostics"]["overall_rms_db"],
        params["deharsh_freq1"], params["deharsh_db1"],
        params["deharsh_freq2"], params["deharsh_db2"],
        params["high_shelf_db"],
        params["bass_boost_db"], params["bass_boost_freq"],
        params["body_boost_db"], params["body_boost_freq"],
        params["saturation_drive"],
        params["ladder_cutoff"],
        params["comp_threshold"],
        params["comp_ratio"],
        f" reverb={params['reverb_wet_level']:.2f}wet" if vocal_mode else "",
    )

    # ── Stages 1–3: EQ cleanup + body shaping [Pedalboard chain 1] ───────────
    chain1 = Pedalboard([
        # Stage 1: Remove sub-bass rumble and DC
        HighpassFilter(cutoff_frequency_hz=30.0),
        # Stage 2: De-harshness (mix: metallic sheen zone / vocal: sibilance zone)
        PeakFilter(cutoff_frequency_hz=params["deharsh_freq1"], gain_db=params["deharsh_db1"], q=1.0),
        PeakFilter(cutoff_frequency_hz=params["deharsh_freq2"], gain_db=params["deharsh_db2"], q=0.8),
        HighShelfFilter(cutoff_frequency_hz=10000.0, gain_db=params["high_shelf_db"]),
        # Stage 3: Body (mix: warmth+fullness / vocal: chest resonance+presence)
        LowShelfFilter(cutoff_frequency_hz=params["bass_boost_freq"], gain_db=params["bass_boost_db"]),
        PeakFilter(cutoff_frequency_hz=params["body_boost_freq"], gain_db=params["body_boost_db"], q=0.5),
    ])
    audio = chain1(audio, sr)

    # ── Stage 4: Analog saturation [numpy] ───────────────────────────────────
    audio = analog_saturate(
        audio,
        drive=params["saturation_drive"],
        asymmetry=params["saturation_asymmetry"],
    )

    # ── Stages 5–6: Tape rolloff + (optional reverb) + compression ───────────
    chain2_plugins = [
        # Stage 5: Moog-style 24dB/oct LPF — analog tape HF rolloff character
        LadderFilter(
            mode=LadderFilter.Mode.LPF24,
            cutoff_hz=params["ladder_cutoff"],
            resonance=params["ladder_resonance"],
            drive=params["ladder_drive"],
        ),
    ]

    if vocal_mode:
        # Stage 5.5: Short room reverb — removes the "in a computer" dryness
        # Even 8% wet transforms dry AI vocals into something that feels recorded
        chain2_plugins.append(
            Reverb(
                room_size=params["reverb_room_size"],
                damping=params["reverb_damping"],
                wet_level=params["reverb_wet_level"],
                # dry_level = 1 - wet_level so total energy stays constant (not additive)
                dry_level=1.0 - params["reverb_wet_level"],
            )
        )

    # Stage 6: Compression (glue for mix / vocal dynamics control)
    chain2_plugins.append(
        Compressor(
            threshold_db=params["comp_threshold"],
            ratio=params["comp_ratio"],
            attack_ms=params["comp_attack_ms"],
            release_ms=params["comp_release_ms"],
        )
    )

    audio = Pedalboard(chain2_plugins)(audio, sr)

    # ── Stage 7: Loudness matching [numpy] ───────────────────────────────────
    # Critical for an honest A/B: output must match input loudness, not be louder.
    # (Louder always sounds "better" to human ears — we must remove that bias.)
    #
    # Problem: RMS-only matching is fooled by compression. Compression reduces crest
    # factor (peak-to-RMS ratio) — there are fewer quiet moments, so the audio feels
    # louder even when RMS is identical. We apply a crest-factor penalty to compensate.
    #
    # penalty = sqrt(output_crest / input_crest), clamped [0.6, 1.0]
    # When compression flattened the dynamics, output_crest < input_crest → penalty < 1 → pull back gain.
    _out64      = audio.astype(np.float64)
    output_rms  = float(np.sqrt(np.mean(_out64 ** 2))) + _EPS
    output_peak = float(np.max(np.abs(_out64))) + _EPS
    output_crest = output_peak / output_rms
    # Penalty: if output is less dynamic than input (typical after compression), reduce gain
    crest_penalty = float(np.clip((output_crest / input_crest) ** 0.5, 0.6, 1.0))
    gain_linear = float(np.clip((input_rms / output_rms) * crest_penalty, 0.25, 4.0))
    audio = (_out64 * gain_linear).astype(np.float32)

    # ── Safety limiter ────────────────────────────────────────────────────────
    # -0.5 dBFS ceiling — streaming-platform safe (Spotify/Apple Music standard)
    limiter = Pedalboard([Limiter(threshold_db=-0.5, release_ms=50.0)])
    audio = limiter(audio, sr)

    return audio.astype(np.float32)


# ── Analysis Report ───────────────────────────────────────────────────────────

def get_analysis_report(audio: np.ndarray, sr: int, intensity: float = 0.5, vocal_mode: bool = False) -> dict:
    """
    Return a JSON-serializable analysis report: what was detected and what
    parameters would be applied at the given intensity and mode.

    Used by the POST /test-edit/warmth/analyze endpoint.
    """
    intensity = float(np.clip(intensity, 0.0, 1.0))
    analysis  = analyze_spectrum(audio, sr)
    params    = compute_warmth_params(analysis, intensity, vocal_mode=vocal_mode)
    diag      = analysis["diagnostics"]
    profile   = analysis["spectral_profile"]

    # Build a human-readable summary of what was detected
    issues: list[str] = []
    if diag["harshness_ratio"] > 1.1:
        issues.append("elevated high-mid energy (2–6 kHz metallic sheen)")
    if diag["spectral_tilt"] > -0.5:
        issues.append("bright spectral tilt (harsh high frequencies)")
    if profile["bass"] < 10:
        issues.append("weak low-end (thin bass)")
    if diag["mid_scoop_ratio"] < 0.35:
        issues.append("hollow midrange (frequency masking between instruments)")
    if diag["crest_factor_db"] < 8:
        issues.append("heavily compressed dynamics (limited headroom)")

    if vocal_mode:
        issues.append("vocal mode active — sibilance de-essing, chest resonance boost, room reverb, gentle compression")

    if issues:
        summary = f"Detected: {'; '.join(issues)}. Applying {'vocal-optimised' if vocal_mode else 'adaptive analog'} warmth processing."
    else:
        summary = f"Audio has balanced frequency content. Applying light {'vocal ' if vocal_mode else ''}analog character enhancement."

    return {
        "spectral_profile":    analysis["spectral_profile"],
        "diagnostics":         analysis["diagnostics"],
        "planned_adjustments": params,
        "vocal_mode":          vocal_mode,
        "summary":             summary,
    }
