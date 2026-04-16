"""
AI Podcast Producer Service
============================
DSP pipeline that turns raw podcast recordings into production-ready episodes.

Pipeline
--------
1. Optional vocal isolation via demucs (sync subprocess) + noise gate
2. Voice EQ & leveling chain (HPF → EQ → de-harsh → compression)
3. LUFS normalization to podcast standard (-16 LUFS)
4. Optional: attach background music with auto-ducking under speech
5. Limiter at -1 dBFS

NOTE: demucs on a 60-minute audio file can take 5–15 minutes of CPU time.
For production use, migrate `produce_podcast` to a Celery task so it does not
block the FastAPI event loop. The current `run_in_threadpool` approach is only
safe for short clips (< 5 minutes) in development.
"""

import logging
import os
import sys
import subprocess
import tempfile

import numpy as np
from pedalboard import (
    Compressor,
    HighpassFilter,
    HighShelfFilter,
    Limiter,
    NoiseGate,
    PeakFilter,
    Pedalboard,
)
from pedalboard.io import AudioFile

from services.mastering_service import apply_lufs_gain, measure_lufs

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────
_PODCAST_TARGET_LUFS = -16.0
_LIMITER_CEILING_DB  = -1.0


# ── 1. noise gate ─────────────────────────────────────────────────────────────

def apply_spectral_noise_gate(
    vocal_audio: np.ndarray,
    sr: int,
    threshold_db: float = -50.0,
) -> np.ndarray:
    """
    Apply a spectral noise gate to remove background hiss and room noise.

    Uses pedalboard.NoiseGate which implements a broadband gate with
    fast/slow time constants. Threshold_db should be set just above the
    noise floor; default -50dB works for most mic recordings.
    """
    chain = Pedalboard([
        NoiseGate(
            threshold_db=threshold_db,
            ratio=10.0,
            attack_ms=5.0,
            release_ms=100.0,
        )
    ])
    return chain(vocal_audio, sr)


# ── 2. voice EQ & leveling ────────────────────────────────────────────────────

def apply_voice_eq(vocal_audio: np.ndarray, sr: int) -> np.ndarray:
    """
    Podcast-standard voice processing chain:

    HPF 80Hz      — remove mic rumble and plosive low-end
    PeakFilter    — -2dB at 200Hz: reduce boxiness / room buildup
    PeakFilter    — +1.5dB at 3kHz: presence / intelligibility
    HighShelf     — -1dB at 10kHz: tame harshness on bright mics
    Compressor    — 3:1, 10ms attack, 80ms release: dynamic control
    """
    chain = Pedalboard([
        HighpassFilter(cutoff_frequency_hz=80.0),
        PeakFilter(cutoff_frequency_hz=200.0,  gain_db=-2.0,  q=0.9),
        PeakFilter(cutoff_frequency_hz=3000.0, gain_db=1.5,   q=1.2),
        HighShelfFilter(cutoff_frequency_hz=10000.0, gain_db=-1.0),
        Compressor(threshold_db=-20.0, ratio=3.0, attack_ms=10.0, release_ms=80.0),
    ])
    return chain(vocal_audio, sr)


# ── 3. speech activity detection ─────────────────────────────────────────────

def compute_speech_activity(
    speech_audio: np.ndarray,
    sr: int,
    frame_size_ms: float = 50.0,
    threshold_db: float = -40.0,
) -> np.ndarray:
    """
    Detect frames where speech is present.

    Returns a binary float32 array of shape (n_frames,):
      1.0 = speech active, 0.0 = silence / background.

    Uses RMS energy per 50ms frame compared to a fixed dB threshold.
    """
    frame_size = int(sr * frame_size_ms / 1000.0)
    if frame_size < 1:
        frame_size = 1

    # Collapse to mono for detection
    mono = speech_audio.mean(axis=0) if speech_audio.ndim == 2 else speech_audio
    n_frames = max(1, len(mono) // frame_size)

    activity = np.zeros(n_frames, dtype=np.float32)
    threshold_linear = 10.0 ** (threshold_db / 20.0)

    for i in range(n_frames):
        chunk = mono[i * frame_size : (i + 1) * frame_size]
        rms = float(np.sqrt(np.mean(chunk ** 2) + 1e-12))
        activity[i] = 1.0 if rms >= threshold_linear else 0.0

    return activity


# ── 4. ducking envelope ───────────────────────────────────────────────────────

def compute_duck_envelope(
    activity: np.ndarray,
    sr: int,
    frame_size_ms: float = 50.0,
    duck_db: float = -18.0,
    attack_frames: int = 4,
    release_frames: int = 10,
) -> np.ndarray:
    """
    Build a per-sample gain envelope that ducks music when speech is active.

    When speech is active the envelope drops to duck_db (linear); when silent
    it returns to 0dB (1.0). Exponential smoothing with attack / release
    frame counts prevents clicks at boundaries.

    Returns a float32 array of shape (n_samples,).
    """
    duck_linear = float(10.0 ** (duck_db / 20.0))   # e.g. -18dB ≈ 0.126
    n_frames    = len(activity)
    frame_size  = int(sr * frame_size_ms / 1000.0)
    n_samples   = n_frames * frame_size

    # Build per-frame gain using exponential smoothing
    gain_frames = np.ones(n_frames, dtype=np.float64)
    current_gain = 1.0
    alpha_attack  = 1.0 / max(attack_frames,  1)
    alpha_release = 1.0 / max(release_frames, 1)

    for i in range(n_frames):
        target = duck_linear if activity[i] > 0.5 else 1.0
        alpha  = alpha_attack if target < current_gain else alpha_release
        current_gain = current_gain + alpha * (target - current_gain)
        gain_frames[i] = current_gain

    # Upsample frame gains to sample level
    envelope = np.repeat(gain_frames, frame_size).astype(np.float32)
    return envelope


# ── 5. apply ducking ──────────────────────────────────────────────────────────

def apply_ducking(music_audio: np.ndarray, envelope: np.ndarray) -> np.ndarray:
    """
    Multiply music by the ducking envelope.

    `music_audio` shape: (channels, samples) or (samples,)
    `envelope`    shape: (samples,)

    Trims / pads envelope to match audio length.
    """
    n = music_audio.shape[-1]
    env = envelope[:n] if len(envelope) >= n else np.pad(envelope, (0, n - len(envelope)), constant_values=1.0)
    if music_audio.ndim == 2:
        return (music_audio * env[np.newaxis, :]).astype(np.float32)
    return (music_audio * env).astype(np.float32)


# ── 6. crossfade join ─────────────────────────────────────────────────────────

def crossfade_join(a: np.ndarray, b: np.ndarray, sr: int, fade_ms: float = 500.0) -> np.ndarray:
    """
    Join two audio arrays with a linear crossfade overlap at the junction.

    Both arrays must have the same number of channels and sample rate.
    If either is shorter than the fade length, the fade is clamped.

    Returns concatenated array (channels, samples) or (samples,).
    """
    fade_samples = int(sr * fade_ms / 1000.0)
    # Clamp to shortest array
    fade_samples = min(fade_samples, a.shape[-1], b.shape[-1])

    if fade_samples < 2:
        # Too short — just concatenate
        return np.concatenate([a, b], axis=-1)

    ramp_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    ramp_in  = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)

    if a.ndim == 2:
        ramp_out = ramp_out[np.newaxis, :]
        ramp_in  = ramp_in[np.newaxis, :]

    a_body    = a[..., :-fade_samples]
    a_tail    = a[..., -fade_samples:] * ramp_out
    b_head    = b[..., :fade_samples]  * ramp_in
    b_body    = b[..., fade_samples:]

    overlap = a_tail + b_head
    return np.concatenate([a_body, overlap, b_body], axis=-1)


# ── 7. build episode with music ───────────────────────────────────────────────

def build_podcast_episode(
    speech_audio: np.ndarray,
    music_audio: np.ndarray,
    sr: int,
    intro_duration_s: float = 8.0,
    outro_duration_s: float = 8.0,
    duck_db: float = -18.0,
) -> tuple[np.ndarray, dict]:
    """
    Attach background music as intro/outro and duck it under speech.

    Steps:
    1. Extract intro clip from start of music, outro clip from end
    2. Loop music bed to cover full speech length
    3. Compute speech activity → ducking envelope → apply to music bed
    4. Mix ducked music bed with speech (clip to [-1, 1])
    5. Crossfade-join: intro → body → outro
    6. Return final stereo mix and a dict with timing info
    """
    # ── channels must match ──────────────────────────────────────────────────
    # Ensure both are 2-channel (stereo)
    def to_stereo(audio: np.ndarray) -> np.ndarray:
        if audio.ndim == 1:
            return np.stack([audio, audio], axis=0)
        if audio.shape[0] == 1:
            return np.concatenate([audio, audio], axis=0)
        return audio

    speech = to_stereo(speech_audio)
    music  = to_stereo(music_audio)

    # Resample music to speech sr if needed (should already match from router)
    # (omitted: both come through _read_audio which normalises to detected sr)

    intro_samples = int(intro_duration_s * sr)
    outro_samples = int(outro_duration_s * sr)
    speech_samples = speech.shape[-1]

    # ── extract intro / outro from music ────────────────────────────────────
    music_len = music.shape[-1]
    intro_clip = music[..., :min(intro_samples, music_len)]
    outro_clip = music[..., max(0, music_len - outro_samples):]

    # ── loop music bed to speech length ─────────────────────────────────────
    if music_len < speech_samples:
        repeats = int(np.ceil(speech_samples / music_len))
        music_bed = np.tile(music, (1, repeats))[..., :speech_samples]
    else:
        music_bed = music[..., :speech_samples]

    # ── compute speech activity on the processed speech ──────────────────────
    activity = compute_speech_activity(speech, sr, frame_size_ms=50.0, threshold_db=-40.0)
    frame_size_ms = 50.0
    frame_size = int(sr * frame_size_ms / 1000.0)
    envelope = compute_duck_envelope(activity, sr, frame_size_ms, duck_db)

    # ── duck music bed ────────────────────────────────────────────────────────
    ducked_bed = apply_ducking(music_bed, envelope)

    # ── mix: clamp to [-1, 1] ────────────────────────────────────────────────
    body_mix = np.clip(speech + ducked_bed, -1.0, 1.0).astype(np.float32)

    # ── join: intro → body → outro with crossfades ───────────────────────────
    result = crossfade_join(intro_clip, body_mix, sr, fade_ms=500.0)
    result = crossfade_join(result, outro_clip, sr, fade_ms=500.0)

    timing = {
        "intro_duration_s":  round(intro_clip.shape[-1] / sr, 2),
        "outro_duration_s":  round(outro_clip.shape[-1] / sr, 2),
        "speech_duration_s": round(speech_samples / sr, 2),
        "total_duration_s":  round(result.shape[-1] / sr, 2),
    }
    return result.astype(np.float32), timing


# ── 8. demucs sync ────────────────────────────────────────────────────────────

def run_demucs_separation_sync(input_path: str, output_dir: str) -> dict[str, str]:
    """
    Run demucs htdemucs model synchronously in a subprocess.

    Returns a dict of stem_name → absolute file path, e.g.:
      {"vocals": "/tmp/…/htdemucs/…/vocals.wav", "drums": …, …}

    NOTE: This call blocks for the duration of demucs processing.
    For files > 5 minutes migrate to a Celery task.
    """
    import re

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    # Sanitise base_name the same way demucs does (non-alphanumeric → _)
    base_name_sanitised = re.sub(r"[^A-Za-z0-9._-]", "_", base_name)

    command = [sys.executable, "-m", "demucs", "--out", output_dir, input_path]
    logger.info("Running demucs: %s", " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"demucs failed: {result.stderr[:400]}")

    stems = {}
    stem_dir = os.path.join(output_dir, "htdemucs", base_name_sanitised)
    for stem in ("vocals", "drums", "bass", "other"):
        path = os.path.join(stem_dir, f"{stem}.wav")
        if os.path.exists(path):
            stems[stem] = path

    if not stems:
        raise RuntimeError(
            f"demucs ran but no stem files found in {stem_dir}. "
            f"stderr: {result.stderr[:200]}"
        )
    return stems


# ── 9. main pipeline ──────────────────────────────────────────────────────────

def produce_podcast(
    speech_audio: np.ndarray,
    sr_speech: int,
    music_audio: np.ndarray | None,
    sr_music: int | None,
    options: dict,
) -> tuple[np.ndarray, dict]:
    """
    Full podcast production pipeline.

    Options dict keys (all optional, have defaults):
      noise_reduction   bool  default True  — run demucs + noise gate
      voice_eq          bool  default True  — apply voice EQ/compression chain
      add_music         bool  default True  — attach intro/outro + duck
      duck_db           float default -18.0 — music duck level in dB
      intro_duration_s  float default 8.0
      outro_duration_s  float default 8.0

    NOTE: noise_reduction=True runs demucs synchronously via subprocess.
    On long audio (30–60 min) this takes 5–15 minutes CPU. In production
    this must run inside a Celery task, NOT run_in_threadpool.
    """
    noise_reduction  = bool(options.get("noise_reduction",  True))
    voice_eq         = bool(options.get("voice_eq",         True))
    add_music        = bool(options.get("add_music",        True)) and music_audio is not None
    duck_db          = float(options.get("duck_db",         -18.0))
    intro_duration_s = float(options.get("intro_duration_s", 8.0))
    outro_duration_s = float(options.get("outro_duration_s", 8.0))

    audio    = speech_audio.copy()
    sr       = sr_speech
    changes  = []
    timing   = {}

    speech_duration_s = round(audio.shape[-1] / sr, 2)

    # ── Stage 1: noise reduction ──────────────────────────────────────────────
    if noise_reduction:
        tmp_input  = None
        tmp_outdir = None
        try:
            # Write speech to a temp WAV for demucs
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_input = f.name
            with AudioFile(tmp_input, "w", samplerate=sr, num_channels=audio.shape[0]) as af:
                af.write(audio)

            tmp_outdir = tempfile.mkdtemp()
            stems = run_demucs_separation_sync(tmp_input, tmp_outdir)
            # Read the vocals stem
            with AudioFile(stems["vocals"]) as af:
                vocals = af.read(af.frames)
            if vocals.dtype != np.float32:
                vocals = vocals.astype(np.float32)
            # Apply noise gate on top of demucs vocal isolation
            vocals = apply_spectral_noise_gate(vocals, sr, threshold_db=-50.0)
            audio = vocals
            changes.append("Vocal isolation (demucs htdemucs) applied")
            changes.append("Spectral noise gate applied")
        except Exception as e:
            logger.warning("Noise reduction failed, skipping: %s", e)
            changes.append(f"Noise reduction skipped: {e}")
        finally:
            if tmp_input and os.path.exists(tmp_input):
                os.unlink(tmp_input)
            if tmp_outdir:
                import shutil
                shutil.rmtree(tmp_outdir, ignore_errors=True)
    else:
        changes.append("Noise reduction skipped (disabled)")

    # ── Stage 2: voice EQ & leveling ─────────────────────────────────────────
    if voice_eq:
        audio = apply_voice_eq(audio, sr)
        changes.append("Voice EQ applied (HPF 80Hz, presence boost 3kHz, 3:1 compression)")

    # ── Stage 3: LUFS normalisation to -16 LUFS ──────────────────────────────
    before_lufs = measure_lufs(audio, sr)
    if before_lufs > -120.0:
        audio, gain_db = apply_lufs_gain(audio, _PODCAST_TARGET_LUFS, before_lufs)
        after_lufs = measure_lufs(audio, sr)
        changes.append(
            f"LUFS normalised: {before_lufs:.1f} → {after_lufs:.1f} LUFS "
            f"(gain {'+' if gain_db >= 0 else ''}{gain_db:.1f} dB)"
        )
    else:
        after_lufs = before_lufs
        changes.append("LUFS normalisation skipped (near-silent audio)")

    # ── Stage 4: background music + ducking ───────────────────────────────────
    if add_music and music_audio is not None:
        # Resample music to speech sr if needed
        if sr_music != sr:
            import librosa
            if music_audio.ndim == 2:
                channels = [librosa.resample(music_audio[c], orig_sr=sr_music, target_sr=sr)
                            for c in range(music_audio.shape[0])]
                music_resampled = np.stack(channels, axis=0).astype(np.float32)
            else:
                music_resampled = librosa.resample(music_audio, orig_sr=sr_music, target_sr=sr).astype(np.float32)
        else:
            music_resampled = music_audio

        audio, timing = build_podcast_episode(
            audio, music_resampled, sr,
            intro_duration_s=intro_duration_s,
            outro_duration_s=outro_duration_s,
            duck_db=duck_db,
        )
        changes.append(
            f"Background music attached — {timing['intro_duration_s']}s intro, "
            f"{timing['outro_duration_s']}s outro"
        )
        changes.append(f"Music auto-ducked to {duck_db:.0f} dB under speech")
    else:
        if not add_music:
            changes.append("Music attachment skipped (disabled or no music provided)")
        timing["speech_duration_s"] = speech_duration_s
        timing["total_duration_s"]  = round(audio.shape[-1] / sr, 2)

    # ── Stage 5: limiter ──────────────────────────────────────────────────────
    limiter_chain = Pedalboard([Limiter(threshold_db=_LIMITER_CEILING_DB, release_ms=50.0)])
    audio = limiter_chain(audio, sr)
    changes.append(f"True-peak limiter at {_LIMITER_CEILING_DB} dBFS")

    report = {
        "before_lufs":       round(before_lufs, 1),
        "after_lufs":        round(after_lufs,  1),
        "target_lufs":       _PODCAST_TARGET_LUFS,
        "speech_duration_s": speech_duration_s,
        "total_duration_s":  round(audio.shape[-1] / sr, 2),
        "noise_reduction":   noise_reduction,
        "voice_eq":          voice_eq,
        "music_added":       add_music and music_audio is not None,
        "duck_db":           duck_db,
        "changes":           changes,
        **timing,
    }
    return audio.astype(np.float32), report
