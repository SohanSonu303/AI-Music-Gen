"""
Reference Track Matching Service
==================================
Analyses a reference track and applies its sonic character to a target track.

Pipeline (match_to_reference):
  1. compute_power_spectrum       — windowed FFT average spectrum for both tracks
  2. compute_spectral_correction  — ref − target correction curve, smoothed + clamped
  3. correction_to_eq_bands       — map continuous curve to 10 parametric EQ bands
  4. apply_spectral_eq            — apply EQ bands via pedalboard PeakFilters
  5. measure_dynamics_profile     — crest factor, RMS, dynamic range for both
  6. apply_dynamics_match         — proportional compression if ref is more compressed
  7. measure_stereo_width         — M-S width measurement for both
  8. apply_stereo_match           — widen/narrow to match reference stereo image
  9. crest-factor-aware loudness match (Stage 7 pattern from warmth_service)
 10. Safety limiter -1.0 dBFS

Bonus — extract_vibe_prompt:
  Extracts BPM, key, mode, and spectral profile from a reference track, then
  uses an LLM to generate a ready-to-use MusicGPT prompt from those fingerprints.
"""

import json
import logging

import librosa
import numpy as np
from pedalboard import Compressor, Limiter, Pedalboard, PeakFilter
from scipy.ndimage import gaussian_filter1d

from services.enhancer_service import stereo_widen
from services.warmth_service import analyze_spectrum

logger = logging.getLogger(__name__)

_EPS = 1e-10

# Krumhansl-Schmuckler key-finding profiles
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


# ── Spectral Analysis ──────────────────────────────────────────────────────────

def compute_power_spectrum(
    audio: np.ndarray, sr: int, n_fft: int = 16384
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute average power spectrum using windowed FFT (Hann window, 50% overlap).

    Parameters
    ----------
    audio : (channels, samples) float32
    sr    : sample rate
    n_fft : FFT size — larger = more frequency resolution

    Returns
    -------
    (freqs, power_db) — shape (n_fft//2+1,) each
    freqs in Hz, power_db in dBFS-relative
    """
    mono = audio.mean(axis=0).astype(np.float64)
    hop = n_fft // 2
    window = np.hanning(n_fft)
    n_bins = n_fft // 2 + 1

    power_acc = np.zeros(n_bins, dtype=np.float64)
    n_windows = 0

    for start in range(0, len(mono) - n_fft + 1, hop):
        frame = mono[start : start + n_fft] * window
        mag = np.abs(np.fft.rfft(frame))
        power_acc += mag ** 2
        n_windows += 1

    if n_windows == 0:
        # Audio shorter than n_fft — zero-pad
        frame = np.zeros(n_fft)
        frame[: len(mono)] = mono * window[: len(mono)]
        power_acc = np.abs(np.fft.rfft(frame)) ** 2
        n_windows = 1

    avg_power = power_acc / n_windows
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    # Convert to dB (avoid log(0))
    power_db = 10.0 * np.log10(avg_power + _EPS)

    return freqs, power_db


def compute_spectral_correction_db(
    ref_power_db: np.ndarray,
    target_power_db: np.ndarray,
    freqs: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute a smoothed EQ correction curve: correction = ref - target.

    Smoothed with gaussian_filter1d (sigma=20 bins) to avoid over-correcting
    narrow peaks. Clamped to ±12 dB to prevent destructive boosts.

    Returns (freqs, correction_db_smoothed)
    """
    raw_correction = ref_power_db - target_power_db

    # Smooth to get a broad tonal correction (not a surgical EQ)
    smoothed = gaussian_filter1d(raw_correction, sigma=20)

    # Clamp to ±12 dB — hard limit per the plan
    clamped = np.clip(smoothed, -12.0, 12.0)

    return freqs, clamped


def correction_to_eq_bands(
    freqs: np.ndarray,
    correction_db: np.ndarray,
    n_bands: int = 10,
) -> list[dict]:
    """
    Map a continuous correction curve to n_bands parametric EQ PeakFilter settings.

    Center frequencies are log-spaced from 60 Hz to 16 kHz.
    Each band's gain = average correction in a ±0.3 octave window around its center.
    Bands where |gain_db| < 0.3 dB are skipped (no-op threshold).

    Returns list of {freq, gain_db, q} dicts.
    """
    centers = np.logspace(np.log10(60.0), np.log10(16000.0), n_bands)
    bands = []
    for fc in centers:
        # ±0.3 octave window
        f_lo = fc * 2 ** (-0.3)
        f_hi = fc * 2 ** (0.3)
        mask = (freqs >= f_lo) & (freqs <= f_hi)
        if not mask.any():
            continue
        gain = float(np.mean(correction_db[mask]))
        if abs(gain) < 0.3:
            continue
        bands.append({"freq": round(float(fc), 1), "gain_db": round(gain, 2), "q": 1.0})

    return bands


def apply_spectral_eq(
    audio: np.ndarray, sr: int, bands: list[dict]
) -> np.ndarray:
    """Apply EQ correction bands via pedalboard PeakFilters."""
    plugins = [
        PeakFilter(cutoff_frequency_hz=b["freq"], gain_db=b["gain_db"], q=b["q"])
        for b in bands
    ]
    if not plugins:
        return audio
    return Pedalboard(plugins)(audio, sr)


# ── Dynamics Matching ──────────────────────────────────────────────────────────

def measure_dynamics_profile(audio: np.ndarray, sr: int) -> dict:
    """
    Measure dynamics profile of an audio signal.

    Returns dict with:
      crest_factor_db  — peak/RMS in dB (high = dynamic, low = compressed)
      rms_db           — overall RMS level in dBFS
      dynamic_range_db — 90th-10th percentile spread of 100ms RMS windows
    """
    mono = audio.mean(axis=0).astype(np.float64)
    frame_size = int(sr * 0.1)  # 100ms frames

    rms_overall = float(np.sqrt(np.mean(mono ** 2))) + _EPS
    peak = float(np.max(np.abs(mono))) + _EPS
    crest_factor_db = float(20.0 * np.log10(peak / rms_overall))
    rms_db = float(20.0 * np.log10(rms_overall))

    # Frame-level RMS for dynamic range
    n_frames = len(mono) // frame_size
    if n_frames >= 4:
        frame_rms = np.array([
            np.sqrt(np.mean(mono[i * frame_size : (i + 1) * frame_size] ** 2)) + _EPS
            for i in range(n_frames)
        ])
        frame_rms_db = 20.0 * np.log10(frame_rms)
        dynamic_range_db = float(np.percentile(frame_rms_db, 90) - np.percentile(frame_rms_db, 10))
    else:
        dynamic_range_db = crest_factor_db  # fallback for very short clips

    return {
        "crest_factor_db": round(crest_factor_db, 2),
        "rms_db": round(rms_db, 2),
        "dynamic_range_db": round(dynamic_range_db, 2),
    }


def apply_dynamics_match(
    audio: np.ndarray,
    sr: int,
    ref_profile: dict,
    target_profile: dict,
) -> tuple[np.ndarray, str]:
    """
    Match target dynamics to reference.

    If reference is more compressed (lower crest_factor_db), apply proportional
    compression to bring target closer. If reference is more dynamic, skip
    (expansion is risky and rarely needed for AI-generated tracks).

    Returns (processed_audio, description_string).
    """
    delta = target_profile["crest_factor_db"] - ref_profile["crest_factor_db"]

    if delta <= 1.0:
        # Already similar or target is more compressed — nothing to do
        return audio, "Dynamics already similar — no compression applied"

    # Proportional ratio: each 6dB of crest-factor difference adds ~1:1 to ratio
    ratio = 1.0 + max(0.0, delta / 6.0)
    ratio = float(np.clip(ratio, 1.2, 4.0))
    threshold = ref_profile["rms_db"] - 6.0

    chain = Pedalboard([
        Compressor(
            threshold_db=threshold,
            ratio=ratio,
            attack_ms=30.0,
            release_ms=150.0,
        )
    ])
    processed = chain(audio, sr)
    desc = (
        f"Compression {ratio:.1f}:1 @ {threshold:.0f}dB threshold "
        f"(crest delta: {delta:.1f}dB)"
    )
    return processed, desc


# ── Stereo Width Matching ──────────────────────────────────────────────────────

def measure_stereo_width(audio: np.ndarray) -> float:
    """
    Measure stereo width using mid-side analysis.

    width = side_rms / (mid_rms + side_rms)
    Returns 0.0 (mono) to ~0.5+ (wide stereo).
    Mono audio (1 channel) always returns 0.0.
    """
    if audio.shape[0] < 2:
        return 0.0
    L, R = audio[0].astype(np.float64), audio[1].astype(np.float64)
    mid  = (L + R) / 2.0
    side = (L - R) / 2.0
    mid_rms  = float(np.sqrt(np.mean(mid  ** 2))) + _EPS
    side_rms = float(np.sqrt(np.mean(side ** 2))) + _EPS
    return round(side_rms / (mid_rms + side_rms), 3)


def apply_stereo_match(
    audio: np.ndarray,
    ref_width: float,
    target_width: float,
) -> tuple[np.ndarray, str]:
    """
    Adjust stereo width to match reference.

    Widening: use stereo_widen from enhancer_service.
    Narrowing: M-S technique — reduce side level relative to mid.
    Adjustment clamped to ±0.4 to avoid extreme stereo artifacts.
    Mono audio (1 channel) is passed through unchanged.
    """
    if audio.shape[0] < 2:
        return audio, "Mono audio — stereo match skipped"

    delta = float(np.clip(ref_width - target_width, -0.4, 0.4))

    if abs(delta) < 0.02:
        return audio, f"Stereo width already similar (ref={ref_width:.2f}, target={target_width:.2f})"

    if delta > 0:
        # Widen: use the existing stereo_widen function (mid-side expansion)
        processed = stereo_widen(audio, width=delta)
        desc = f"Stereo widened +{delta:.2f} (ref={ref_width:.2f}, target={target_width:.2f})"
    else:
        # Narrow: reduce side channel
        L, R = audio[0].astype(np.float64), audio[1].astype(np.float64)
        mid  = (L + R) / 2.0
        side = (L - R) / 2.0
        # Scale down side by (1 + delta) — delta is negative here
        side_scaled = side * max(0.0, 1.0 + delta * 2)
        L_out = (mid + side_scaled).astype(np.float32)
        R_out = (mid - side_scaled).astype(np.float32)
        processed = np.stack([L_out, R_out])
        desc = f"Stereo narrowed {delta:.2f} (ref={ref_width:.2f}, target={target_width:.2f})"

    return processed, desc


# ── Musical Fingerprint ────────────────────────────────────────────────────────

def extract_musical_fingerprint(audio: np.ndarray, sr: int) -> dict:
    """
    Extract BPM, musical key, and mode (major/minor) from audio.

    BPM  : librosa.beat.beat_track
    Key  : chroma_cqt + Krumhansl-Schmuckler key-finding profiles
    """
    mono = audio.mean(axis=0).astype(np.float32)

    # BPM
    tempo, _ = librosa.beat.beat_track(y=mono, sr=sr)
    bpm = round(float(np.atleast_1d(tempo)[0]), 1)

    # Key via chroma + KS profiles
    chroma = librosa.feature.chroma_cqt(y=mono, sr=sr)
    chroma_mean = chroma.mean(axis=1)  # shape (12,)

    # Correlate with all 12 major + 12 minor profiles (circular rotations)
    best_score = -np.inf
    best_key = "C"
    best_mode = "major"
    for i in range(12):
        major_score = float(np.corrcoef(np.roll(_KS_MAJOR, i), chroma_mean)[0, 1])
        minor_score = float(np.corrcoef(np.roll(_KS_MINOR, i), chroma_mean)[0, 1])
        if major_score > best_score:
            best_score = major_score
            best_key = _NOTE_NAMES[i]
            best_mode = "major"
        if minor_score > best_score:
            best_score = minor_score
            best_key = _NOTE_NAMES[i]
            best_mode = "minor"

    return {"bpm": bpm, "key": best_key, "mode": best_mode}


# ── Vibe Prompt (LLM) ──────────────────────────────────────────────────────────

_VIBE_SYSTEM_PROMPT = """\
You are an expert music AI prompt engineer. You will receive a JSON object containing
audio analysis data (BPM, musical key/mode, spectral energy bands, and diagnostics).
Your task is to write a vivid, production-ready MusicGPT generation prompt of 80–120
words that captures the sonic identity of the track.

Rules:
- Include tempo, key, mood, instrumentation, genre, and energy level
- Be specific and evocative — avoid generic words like "nice" or "good"
- Do NOT explain what you are doing — output ONLY the prompt text
- Maximum 280 characters total (MusicGPT hard limit)
"""


async def extract_vibe_prompt(audio: np.ndarray, sr: int) -> dict:
    """
    Analyse a reference track and generate a MusicGPT-ready prompt via LLM.

    Returns { prompt: str, fingerprint: dict }
    """
    from services.prompt_service import _call_openrouter  # local import — avoids circular dep

    fingerprint = extract_musical_fingerprint(audio, sr)
    spectral = analyze_spectrum(audio, sr)

    user_content = json.dumps({
        "bpm": fingerprint["bpm"],
        "key": f"{fingerprint['key']} {fingerprint['mode']}",
        "spectral_profile": spectral["spectral_profile"],
        "diagnostics": spectral["diagnostics"],
    }, indent=2)

    prompt_text = await _call_openrouter(_VIBE_SYSTEM_PROMPT, user_content)
    # Truncate to 280 chars hard limit
    if len(prompt_text) > 280:
        prompt_text = prompt_text[:277] + "..."

    return {"prompt": prompt_text.strip(), "fingerprint": fingerprint}


# ── Main Pipeline ──────────────────────────────────────────────────────────────

def match_to_reference(
    target: np.ndarray,
    sr_target: int,
    reference: np.ndarray,
    sr_ref: int,
) -> tuple[np.ndarray, dict]:
    """
    Apply the sonic character of the reference track to the target track.

    Parameters
    ----------
    target    : float32 (channels, samples) — the track to process
    sr_target : sample rate of target
    reference : float32 (channels, samples) — the reference to match
    sr_ref    : sample rate of reference

    Returns
    -------
    (processed_audio, report_dict)

    report_dict shape:
    {
      eq_bands_applied:   [{freq, gain_db, q}, ...],
      dynamics:           {ref, target_before, target_after},
      stereo_width:       {ref, target_before, target_after},
      reference_fingerprint: {bpm, key, mode},
      target_fingerprint:    {bpm, key, mode},
      changes_summary:    [str, ...]
    }
    """
    changes: list[str] = []

    # ── Resample reference to target SR if needed ─────────────────────────────
    if sr_ref != sr_target:
        ref_mono = reference.mean(axis=0).astype(np.float32)
        ref_resampled_mono = librosa.resample(ref_mono, orig_sr=sr_ref, target_sr=sr_target)
        # Rebuild stereo if source was stereo
        if reference.shape[0] == 2:
            ref_r_mono = reference[1].astype(np.float32)
            ref_r_resampled = librosa.resample(ref_r_mono, orig_sr=sr_ref, target_sr=sr_target)
            reference = np.stack([ref_resampled_mono, ref_r_resampled])
        else:
            reference = ref_resampled_mono[np.newaxis, :]
        original_sr_ref = sr_ref
        sr_ref = sr_target
        changes.append(f"Reference resampled from {original_sr_ref}Hz to {sr_target}Hz")

    sr = sr_target

    # ── Pre-measurements ──────────────────────────────────────────────────────
    target_width_before = measure_stereo_width(target)
    ref_width = measure_stereo_width(reference)
    target_dyn_before = measure_dynamics_profile(target, sr)
    ref_dyn = measure_dynamics_profile(reference, sr)

    # Input loudness (for crest-factor-aware match at end)
    _in64 = target.astype(np.float64)
    input_rms  = float(np.sqrt(np.mean(_in64 ** 2))) + _EPS
    input_peak = float(np.max(np.abs(_in64))) + _EPS
    input_crest = input_peak / input_rms

    processed = target.copy()

    # ── Stage 1: Spectral EQ matching ────────────────────────────────────────
    freqs, ref_power_db    = compute_power_spectrum(reference, sr)
    _,     target_power_db = compute_power_spectrum(processed, sr)
    _, correction_db       = compute_spectral_correction_db(ref_power_db, target_power_db, freqs)
    eq_bands               = correction_to_eq_bands(freqs, correction_db)
    processed              = apply_spectral_eq(processed, sr, eq_bands)
    if eq_bands:
        top3 = sorted(eq_bands, key=lambda b: abs(b["gain_db"]), reverse=True)[:3]
        changes.append(
            "Spectral EQ: " + ", ".join(
                f"{b['freq']}Hz {'+' if b['gain_db']>0 else ''}{b['gain_db']}dB"
                for b in top3
            ) + (f" (+{len(eq_bands)-3} more)" if len(eq_bands) > 3 else "")
        )
    else:
        changes.append("Spectral EQ: spectra already similar — no correction needed")

    # ── Stage 2: Dynamics matching ────────────────────────────────────────────
    processed, dyn_desc = apply_dynamics_match(processed, sr, ref_dyn, target_dyn_before)
    changes.append(f"Dynamics: {dyn_desc}")
    target_dyn_after = measure_dynamics_profile(processed, sr)

    # ── Stage 3: Stereo width matching ───────────────────────────────────────
    processed, stereo_desc = apply_stereo_match(processed, ref_width, target_width_before)
    changes.append(f"Stereo: {stereo_desc}")
    target_width_after = measure_stereo_width(processed)

    # ── Stage 4: Crest-factor-aware loudness match (warmth_service pattern) ──
    _out64      = processed.astype(np.float64)
    output_rms  = float(np.sqrt(np.mean(_out64 ** 2))) + _EPS
    output_peak = float(np.max(np.abs(_out64))) + _EPS
    output_crest = output_peak / output_rms
    crest_penalty = float(np.clip((output_crest / input_crest) ** 0.5, 0.6, 1.0))
    gain_linear = float(np.clip((input_rms / output_rms) * crest_penalty, 0.25, 4.0))
    processed = (_out64 * gain_linear).astype(np.float32)
    changes.append(f"Loudness matched (gain {20*np.log10(gain_linear):.1f}dB, crest penalty {crest_penalty:.2f})")

    # ── Stage 5: Safety limiter ───────────────────────────────────────────────
    processed = Pedalboard([Limiter(threshold_db=-1.0, release_ms=50.0)])(processed, sr)
    changes.append("Safety limiter: −1.0 dBFS ceiling")

    # ── Musical fingerprints ──────────────────────────────────────────────────
    ref_fingerprint    = extract_musical_fingerprint(reference, sr)
    target_fingerprint = extract_musical_fingerprint(target, sr)

    logger.info(
        "match_to_reference: eq_bands=%d  dyn_delta=%.1fdB  stereo_delta=%.2f",
        len(eq_bands),
        target_dyn_before["crest_factor_db"] - ref_dyn["crest_factor_db"],
        ref_width - target_width_before,
    )

    report = {
        "eq_bands_applied": eq_bands,
        "dynamics": {
            "ref":           ref_dyn,
            "target_before": target_dyn_before,
            "target_after":  target_dyn_after,
        },
        "stereo_width": {
            "ref":           ref_width,
            "target_before": target_width_before,
            "target_after":  target_width_after,
        },
        "reference_fingerprint": ref_fingerprint,
        "target_fingerprint":    target_fingerprint,
        "changes_summary":       changes,
    }

    return processed.astype(np.float32), report
