"""
Auto Edit Service — Phase 1, 2, 3 & 5
=======================================
Audio analysis, candidate window generation, and editing execution for AIME.

Pipeline overview (full):
  analyze_audio()         ← Phase 2  — BPM, beats, downbeats, segments (librosa)  ✅
  find_candidate_windows()← Phase 3  — beat-snapped trim candidates               ✅
  select_window()         ← Phase 4  — LLM picks best candidate (agents/auto_edit_agent.py) ✅
  execute_trim()          ← Phase 5  — numpy slice + loop + fade-out              ✅
  POST /auto-edit/save    ← Phase 6  — editing_table persistence
"""

import logging
from dataclasses import dataclass
from typing import Optional

import librosa
import numpy as np

logger = logging.getLogger(__name__)

MIN_SOURCE_DURATION: float = 8.0  # seconds — shorter files are rejected with 422

_BEAT_DEVIATION_LIMIT_MS: float = 15.0  # plan success metric


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class SegmentData:
    start: float
    end: float
    energy: float        # normalised RMS (0.0–1.0)
    label: str           # intro | build | peak | outro


@dataclass
class AnalysisResult:
    bpm: float
    duration: float
    beat_times: list[float]
    downbeat_times: list[float]
    segments: list[SegmentData]
    used_beat_fallback: bool = False  # True when librosa beat tracking was unreliable


@dataclass
class Window:
    """A candidate trim window, always aligned to detected downbeats."""
    start: float              # trim start in seconds (snapped to downbeat)
    end: float                # trim end in seconds (snapped to downbeat)
    duration: float           # end - start
    beat_deviation_ms: float  # deviation from nearest downbeat (always 0 — we snap directly)
    energy_score: float       # 0.0–1.0 energy match to user preference
    duration_score: float     # 0.0–1.0 closeness to target_duration
    structural_score: float   # 0.0–1.0 fraction of segments fully covered
    spectral_quality_score: float = 0.5  # 0.0–1.0 audio quality (Phase 15): crest, centroid, harshness
    total_score: float = 0.0  # weighted combination used for ranking
    segment_labels: list[str] = None  # labels of segments overlapping this window
    needs_loop: bool = False  # True when target > source (execute_trim will loop)

    def __post_init__(self):
        if self.segment_labels is None:
            self.segment_labels = []


# ── Phase 2: Audio Analysis ───────────────────────────────────────────────────

def analyze_audio(audio: np.ndarray, sr: int) -> AnalysisResult:
    """
    Extract musical structure from an audio array.

    Parameters
    ----------
    audio : np.ndarray  shape (channels, samples), float32
    sr    : int         sample rate in Hz

    Returns
    -------
    AnalysisResult with bpm, beat_times, downbeat_times, segments, duration.

    Notes
    -----
    - Audio is downmixed to mono *internally* for analysis only.
      The original stereo array is never mutated.
    - Segment count is estimated from duration + BPM (~1 segment per 8 bars).
    - Downbeats use a 4/4 assumption: every 4th detected beat.
    - Segment labels are heuristic; precise labelling is an FR-2 concern.
    """
    duration = audio.shape[1] / sr
    logger.info("analyze_audio: duration=%.2fs sr=%d channels=%d", duration, sr, audio.shape[0])

    # Downmix to mono for librosa (keep original untouched)
    mono = audio.mean(axis=0).astype(np.float32)

    # ── BPM + beat tracking ──────────────────────────────────────────────────
    tempo, beat_frames = librosa.beat.beat_track(y=mono, sr=sr, units="frames")
    # librosa may return a 1-element array in some versions
    bpm = float(np.atleast_1d(tempo)[0])
    beat_times: list[float] = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    logger.info("analyze_audio: bpm=%.1f beats=%d", bpm, len(beat_times))

    # ── Guard: fall back to evenly-spaced grid when beat tracking is unreliable
    # Triggered by ambient/drone audio with no clear transients (very few beats
    # detected or implausibly low BPM). A 120 BPM grid ensures find_candidate_windows
    # still has usable anchor points, and the caller is warned via used_beat_fallback.
    _MIN_RELIABLE_BEATS = 4
    used_beat_fallback = False
    if bpm < 40.0 or len(beat_times) < _MIN_RELIABLE_BEATS:
        logger.warning(
            "analyze_audio: unreliable beat tracking (bpm=%.1f, beats=%d) — "
            "falling back to evenly-spaced 120 BPM grid",
            bpm, len(beat_times),
        )
        used_beat_fallback = True
        bpm = 120.0
        beat_interval = 60.0 / bpm  # 0.5 s per beat
        beat_times = [round(float(t), 4) for t in np.arange(0.0, duration, beat_interval)]
        downbeat_times = [round(float(t), 4) for t in np.arange(0.0, duration, beat_interval * 4)]
        logger.info(
            "analyze_audio: fallback grid — %d beats, %d downbeats",
            len(beat_times), len(downbeat_times),
        )
    else:
        # ── Downbeats: every 4th beat (4/4 assumption) ───────────────────────
        downbeat_frames = beat_frames[::4]
        downbeat_times: list[float] = librosa.frames_to_time(downbeat_frames, sr=sr).tolist()

    # ── Segment boundaries (MFCC agglomerative clustering) ───────────────────
    mfcc = librosa.feature.mfcc(y=mono, sr=sr, n_mfcc=13)
    # Target ~1 segment per 8 bars; clamp between 4 and 16
    bars_total = max(1.0, (bpm / 60.0) * duration / 4.0)
    n_segs = int(np.clip(bars_total / 8, 4, 16))
    # agglomerative needs k < number of frames
    n_segs = min(n_segs, mfcc.shape[1] - 1)

    bound_frames = librosa.segment.agglomerative(mfcc, k=n_segs)
    bound_times: list[float] = librosa.frames_to_time(bound_frames, sr=sr).tolist()

    # Ensure 0.0 and total duration bracket the list
    if not bound_times or bound_times[0] > 0.1:
        bound_times = [0.0] + bound_times
    if bound_times[-1] < duration - 0.1:
        bound_times = bound_times + [duration]

    # ── Segment energies (RMS per segment) ───────────────────────────────────
    raw_energies: list[float] = []
    for i in range(len(bound_times) - 1):
        start_s = int(bound_times[i] * sr)
        end_s = int(bound_times[i + 1] * sr)
        seg = mono[start_s:end_s]
        rms = float(np.sqrt(np.mean(seg ** 2))) if len(seg) > 0 else 0.0
        raw_energies.append(rms)

    # Normalise energies to 0.0–1.0
    max_e = max(raw_energies) if raw_energies else 1.0
    norm_energies = [e / (max_e + 1e-10) for e in raw_energies]

    # ── Spectral features for richer segment labeling (Phase 14) ─────────────
    try:
        chroma_vars, contrasts, onset_densities = _compute_spectral_features(
            mono, sr, bound_times
        )
        logger.info(
            "analyze_audio: spectral features computed — chroma_vars=%s onset_densities=%s",
            [round(v, 2) for v in chroma_vars],
            [round(v, 2) for v in onset_densities],
        )
    except Exception as exc:
        logger.warning("analyze_audio: spectral feature extraction failed (%s) — using energy-only labels", exc)
        chroma_vars, onset_densities = None, None

    # ── Segment labels (spectral-aware when features available) ──────────────
    labels = _label_segments(norm_energies, chroma_vars, onset_densities)

    segments = [
        SegmentData(
            start=bound_times[i],
            end=bound_times[i + 1],
            energy=round(norm_energies[i], 4),
            label=labels[i],
        )
        for i in range(len(norm_energies))
    ]

    logger.info(
        "analyze_audio: segments=%d downbeats=%d labels=%s",
        len(segments), len(downbeat_times), [s.label for s in segments]
    )

    return AnalysisResult(
        bpm=round(bpm, 2),
        duration=round(duration, 3),
        beat_times=[round(t, 4) for t in beat_times],
        downbeat_times=[round(t, 4) for t in downbeat_times],
        segments=segments,
        used_beat_fallback=used_beat_fallback,
    )


def _compute_spectral_features(
    mono: np.ndarray,
    sr: int,
    bound_times: list[float],
) -> tuple[list[float], list[float], list[float]]:
    """
    Compute per-segment spectral features for richer structural labeling.

    Returns three parallel lists aligned to the segment boundaries:
    - chroma_vars   : chroma variance per segment (high = harmonic activity / chorus)
    - contrasts     : mean spectral contrast per segment (high = tonal richness)
    - onset_densities : onset count / segment duration (high = rhythmically dense)

    All lists have length ``len(bound_times) - 1``.
    """
    n_segs = len(bound_times) - 1
    if n_segs <= 0:
        return [], [], []

    # Chroma — harmonic content
    try:
        chroma = librosa.feature.chroma_cqt(y=mono, sr=sr)
    except Exception:
        chroma = librosa.feature.chroma_stft(y=mono, sr=sr)

    # Spectral contrast — separation between spectral peaks and valleys
    try:
        contrast = librosa.feature.spectral_contrast(y=mono, sr=sr)
    except Exception:
        contrast = np.zeros((7, max(1, mono.shape[0] // 512)), dtype=np.float32)

    # Onset envelope for density
    onset_env = librosa.onset.onset_strength(y=mono, sr=sr)
    onset_times = librosa.times_like(onset_env, sr=sr)

    hop_length = 512
    chroma_vars, contrasts, onset_densities = [], [], []

    for i in range(n_segs):
        t0, t1 = bound_times[i], bound_times[i + 1]
        seg_dur = max(t1 - t0, 1e-3)

        f0 = librosa.time_to_frames(t0, sr=sr, hop_length=hop_length)
        f1 = librosa.time_to_frames(t1, sr=sr, hop_length=hop_length)
        f0, f1 = int(f0), int(f1)

        # Chroma variance (measure of harmonic richness / chord changes)
        c_seg = chroma[:, f0:f1] if f1 > f0 else chroma[:, :1]
        chroma_vars.append(float(np.var(c_seg)) if c_seg.size > 0 else 0.0)

        # Mean spectral contrast (proxy for mix fullness)
        k_seg = contrast[:, f0:f1] if f1 > f0 else contrast[:, :1]
        contrasts.append(float(np.mean(k_seg)) if k_seg.size > 0 else 0.0)

        # Onset density (beats/transients per second)
        mask = (onset_times >= t0) & (onset_times < t1)
        n_onsets = int(np.sum(onset_env[mask] > 0.5 * onset_env[mask].max() + 1e-8))
        onset_densities.append(n_onsets / seg_dur)

    # Normalise each feature to [0, 1]
    def _norm(lst: list[float]) -> list[float]:
        mx = max(lst) if lst else 1.0
        return [v / (mx + 1e-10) for v in lst]

    return _norm(chroma_vars), _norm(contrasts), _norm(onset_densities)


def _label_segments(
    norm_energies: list[float],
    chroma_vars: Optional[list[float]] = None,
    onset_densities: Optional[list[float]] = None,
) -> list[str]:
    """
    Assign a structural label to each segment.

    When spectral features are available (Phase 14), labeling uses a
    multi-feature decision tree:

      high energy + high chroma variance                  → "chorus"
      high energy + low chroma variance + high onset      → "peak" / "drop"
      moderate energy + moderate chroma + rising onset    → "build"
      moderate energy + moderate chroma + flat onset      → "verse"
      low energy + any chroma                             → "bridge" (mid-track)
                                                            "intro"  (first quarter)
                                                            "outro"  (last quarter)

    Falls back to the v1 energy-only heuristic when spectral features are absent.

    Labels emitted: intro | verse | build | chorus | peak | drop | bridge | outro
    """
    if not norm_energies:
        return []

    n = len(norm_energies)
    use_spectral = (
        chroma_vars is not None
        and onset_densities is not None
        and len(chroma_vars) == n
        and len(onset_densities) == n
    )

    if not use_spectral:
        # v1 fallback: energy-only heuristic
        peak_idx = int(np.argmax(norm_energies))
        labels: list[str] = []
        for i, e in enumerate(norm_energies):
            if i == 0 and e < 0.5:
                labels.append("intro")
            elif i == peak_idx:
                labels.append("peak")
            elif i < peak_idx:
                labels.append("intro" if e < 0.4 else "build")
            else:
                labels.append("outro" if e < 0.5 else "build")
        return labels

    # ── Spectral multi-feature labeling ──────────────────────────────────────
    labels = []
    for i in range(n):
        e   = norm_energies[i]
        cv  = chroma_vars[i]
        od  = onset_densities[i]

        # Position-based context (intro / outro zones)
        pos = i / max(n - 1, 1)   # 0.0 = first segment, 1.0 = last

        if e < 0.30:
            # Low-energy region
            if pos < 0.25:
                labels.append("intro")
            elif pos > 0.75:
                labels.append("outro")
            else:
                labels.append("bridge")
        elif e >= 0.70:
            # High-energy region
            if cv >= 0.55:
                labels.append("chorus")   # lots of harmonic movement
            elif od >= 0.70:
                labels.append("drop")     # dense transients, low chord variety
            else:
                labels.append("peak")     # sustained high energy
        else:
            # Moderate energy
            if od >= 0.60:
                labels.append("build")    # rising density
            elif cv >= 0.40:
                labels.append("verse")    # melodic, moderate density
            else:
                labels.append("build")    # default moderate

    return labels


# ── Phase 3: Candidate Window Generation ─────────────────────────────────────

def find_candidate_windows(
    analysis: AnalysisResult,
    target_duration: float,
    energy_preference: Optional[str] = None,
    top_k: int = 3,
    strictness: float = 0.5,
    mono: Optional[np.ndarray] = None,
    sr: int = 44100,
) -> list[Window]:
    """
    Generate the top-K beat-accurate candidate trim windows.

    Algorithm
    ---------
    1. Use ``analysis.downbeat_times`` as snap anchors.
    2. For every ordered pair (start_anchor, end_anchor) within ±1 bar of target,
       create a Window candidate.
    3. Score each candidate on FOUR axes; weights depend on ``strictness``:

       strictness=1.0  → 72 / 9 / 9 / 10  (duration dominant)
       strictness=0.5  → 45 / 22.5 / 22.5 / 10  (balanced)
       strictness=0.0  → 18 / 36 / 36 / 10  (musical integrity dominant)

       Spectral quality weight is fixed at 10 % regardless of strictness.
       The remaining 90 % is divided among duration/energy/structure.

       - **duration_score**        — 1.0 when exact, 0.0 at ±1 bar
       - **energy_score**          — 0.0–1.0 match to ``energy_preference``
       - **structural_score**      — fraction of segments fully inside window
       - **spectral_quality_score** — audio quality (crest, centroid, harshness);
                                      requires ``mono`` to be passed (Phase 15)

    4. Return the top ``top_k`` by ``total_score``.

    Special cases
    -------------
    - ``target_duration > source_duration``: returns a single full-file Window
      with ``needs_loop=True``; ``execute_trim`` will handle looping.
    - Fewer than 2 anchor points: returns an empty list (caller should 422).

    Parameters
    ----------
    analysis          : result from ``analyze_audio``
    target_duration   : desired output length in seconds
    energy_preference : "high_energy" | "climax" | "drop" | "chorus" | "verse" |
                        "build" | "chill" | "outro" | "intro_heavy" | None
    top_k             : max candidates to return (default 3)
    strictness        : 0.0–1.0 precision/integrity tradeoff (default 0.5)
    mono              : (samples,) float32 mono array — enables spectral quality scoring
    sr                : sample rate (required when mono is provided)
    """
    strictness = float(np.clip(strictness, 0.0, 1.0))

    # ── Compute weight split from strictness ─────────────────────────────────
    # Spectral quality is fixed at 10%; remaining 90% splits between dur/energy/struct.
    # musical pole (0.0):  dur=0.18, energy=0.36, struct=0.36, spectral=0.10
    # precise pole  (1.0): dur=0.72, energy=0.09, struct=0.09, spectral=0.10
    w_spectral = 0.10
    w_dur      = (0.20 + 0.60 * strictness) * 0.90
    w_energy   = (0.40 - 0.30 * strictness) * 0.90
    w_struct   = (0.40 - 0.30 * strictness) * 0.90
    use_spectral = mono is not None
    logger.info(
        "find_candidate_windows: strictness=%.2f → weights dur=%.2f energy=%.2f "
        "struct=%.2f spectral=%.2f (active=%s)",
        strictness, w_dur, w_energy, w_struct, w_spectral, use_spectral,
    )

    # ── Select anchor points ─────────────────────────────────────────────────
    anchors: list[float] = (
        analysis.downbeat_times
        if len(analysis.downbeat_times) >= 2
        else analysis.beat_times[::4]
    )
    if len(anchors) < 2:
        logger.warning("find_candidate_windows: too few anchors (%d) to form a window", len(anchors))
        return []

    bpm = max(analysis.bpm, 40.0)          # guard against 0-BPM (silent audio)
    bar_duration = 4 * 60.0 / bpm          # seconds per bar (4/4)
    tolerance = bar_duration                # ±1 bar

    # ── Loop case: target longer than source ─────────────────────────────────
    if target_duration > analysis.duration:
        loop_window = Window(
            start=0.0,
            end=analysis.duration,
            duration=analysis.duration,
            beat_deviation_ms=0.0,
            energy_score=0.5,
            duration_score=0.0,
            structural_score=1.0,
            total_score=0.3,
            segment_labels=[s.label for s in analysis.segments],
            needs_loop=True,
        )
        logger.info(
            "find_candidate_windows: target (%.1fs) > source (%.1fs) → loop window",
            target_duration, analysis.duration,
        )
        return [loop_window]

    # ── Generate all valid (start, end) pairs ────────────────────────────────
    candidates: list[Window] = []
    for i, start in enumerate(anchors):
        for end in anchors[i + 1:]:
            w_dur_val = end - start
            if abs(w_dur_val - target_duration) > tolerance:
                continue

            duration_score = 1.0 - abs(w_dur_val - target_duration) / tolerance

            covered_labels, avg_energy, n_complete = _window_segment_info(
                analysis.segments, start, end
            )
            energy_score = _energy_score(
                analysis.segments, start, end, avg_energy, energy_preference
            )

            total_segs = max(len(analysis.segments), 1)
            structural_score = min(n_complete / total_segs, 1.0)

            # Phase 15: spectral quality (requires mono audio)
            sq_score = (
                _spectral_quality_score(mono, sr, start, end)
                if use_spectral else 0.5
            )

            total_score = (
                w_dur      * duration_score
                + w_energy * energy_score
                + w_struct * structural_score
                + w_spectral * sq_score
            )

            candidates.append(Window(
                start=round(start, 4),
                end=round(end, 4),
                duration=round(w_dur_val, 4),
                beat_deviation_ms=0.0,
                energy_score=round(energy_score, 4),
                duration_score=round(duration_score, 4),
                structural_score=round(structural_score, 4),
                spectral_quality_score=round(sq_score, 4),
                total_score=round(total_score, 4),
                segment_labels=covered_labels,
                needs_loop=False,
            ))

    candidates.sort(key=lambda w: w.total_score, reverse=True)

    # Enforce diversity: skip candidates that overlap an already-selected window.
    # This ensures the 3 returned candidates cover genuinely different sections
    # of the track rather than clustering within a few seconds of each other.
    result: list[Window] = []
    for c in candidates:
        overlaps = any(c.start < s.end and c.end > s.start for s in result)
        if not overlaps:
            result.append(c)
            if len(result) == top_k:
                break

    logger.info(
        "find_candidate_windows: %d candidates found (target=%.1fs bpm=%.1f bar=%.2fs), returning top %d",
        len(candidates), target_duration, bpm, bar_duration, len(result),
    )
    if result:
        best = result[0]
        logger.info(
            "find_candidate_windows: best window [%.2f–%.2f] dur=%.2fs score=%.3f labels=%s",
            best.start, best.end, best.duration, best.total_score, best.segment_labels,
        )
    return result


# ── Phase 3 helpers ───────────────────────────────────────────────────────────

def _window_segment_info(
    segments: list[SegmentData],
    start: float,
    end: float,
) -> tuple[list[str], float, int]:
    """
    Compute overlap information between a window [start, end] and all segments.

    Returns
    -------
    covered_labels : list of labels for segments that overlap the window
    avg_energy     : energy-weighted mean of overlapping segments
    n_complete     : count of segments fully contained within the window (±50ms)
    """
    covered_labels: list[str] = []
    energies: list[float] = []
    n_complete = 0

    for seg in segments:
        overlap_start = max(seg.start, start)
        overlap_end = min(seg.end, end)
        if overlap_end <= overlap_start:
            continue

        seg_dur = seg.end - seg.start
        overlap_frac = (overlap_end - overlap_start) / max(seg_dur, 1e-6)
        covered_labels.append(seg.label)
        energies.append(seg.energy * overlap_frac)

        # "complete" if segment is fully inside the window (±50ms tolerance)
        if seg.start >= start - 0.05 and seg.end <= end + 0.05:
            n_complete += 1

    avg_energy = float(np.mean(energies)) if energies else 0.0
    return covered_labels, avg_energy, n_complete


def _label_overlap_score(
    segments: list[SegmentData],
    start: float,
    end: float,
    target_labels: list[str],
    fallback: float,
) -> float:
    """
    Return 1.0 if any segment in the window fully matches one of ``target_labels``,
    0.8 if partially overlapped, else ``fallback``.
    """
    window_len = max(end - start, 0.001)
    best = 0.0
    for s in segments:
        if s.label not in target_labels:
            continue
        overlap = max(0.0, min(end, s.end) - max(start, s.start))
        seg_len = max(s.end - s.start, 0.001)
        # Fully contained in window
        if start <= s.start + 0.1 and end >= s.end - 0.1:
            return 1.0
        # Significant overlap (>50% of segment)
        if overlap / seg_len > 0.5:
            best = max(best, 0.8)
        elif overlap > 0:
            best = max(best, 0.4)
    return best if best > 0 else fallback


def _energy_score(
    segments: list[SegmentData],
    start: float,
    end: float,
    avg_energy: float,
    preference: Optional[str],
) -> float:
    """
    Return 0.0–1.0 score representing how well this window matches ``preference``.

    Preferences
    -----------
    None / unknown  → use avg_energy (higher energy generally preferred)
    "high_energy"   → raw avg_energy of covered segments
    "climax"        → 1.0 if window contains a peak or drop segment
    "drop"          → 1.0 if window contains a drop segment specifically
    "chorus"        → 1.0 if window contains a chorus segment
    "verse"         → 1.0 if window contains a verse segment
    "build"         → 1.0 if window contains a build/riser segment
    "chill"         → inverse of avg_energy (prefer low-energy windows)
    "outro"         → positional score favouring late windows
    "intro_heavy"   → positional score favouring early windows
    """
    _KNOWN = {
        "high_energy", "climax", "drop", "chorus", "verse",
        "build", "chill", "outro", "intro_heavy",
    }
    if preference is None or preference not in _KNOWN:
        return avg_energy

    if preference == "high_energy":
        return avg_energy

    if preference == "climax":
        return _label_overlap_score(segments, start, end, ["peak", "drop", "chorus"], avg_energy)

    if preference == "drop":
        return _label_overlap_score(segments, start, end, ["drop"], avg_energy * 0.6)

    if preference == "chorus":
        return _label_overlap_score(segments, start, end, ["chorus", "peak"], avg_energy * 0.7)

    if preference == "verse":
        return _label_overlap_score(segments, start, end, ["verse"], avg_energy * 0.5)

    if preference == "build":
        return _label_overlap_score(segments, start, end, ["build"], avg_energy * 0.6)

    if preference == "chill":
        # Prefer low-energy windows: invert avg_energy, boost intro/bridge/verse
        chill_bonus = _label_overlap_score(
            segments, start, end, ["intro", "bridge", "verse", "outro"], 0.0
        )
        return float(np.clip((1.0 - avg_energy) * 0.7 + chill_bonus * 0.3, 0.0, 1.0))

    track_dur = segments[-1].end if segments else max(end, 1.0)

    if preference == "outro":
        position_score = start / max(track_dur, 1.0)   # 1.0 near end, 0.0 near start
        outro_bonus = _label_overlap_score(segments, start, end, ["outro", "bridge"], 0.0)
        return float(np.clip(position_score * 0.7 + outro_bonus * 0.3, 0.0, 1.0))

    # "intro_heavy": score = 1.0 at the very start, 0.0 at the very end
    position_score = 1.0 - (start / max(track_dur, 1.0))
    intro_bonus = _label_overlap_score(segments, start, end, ["intro", "verse"], 0.0)
    return float(np.clip(position_score * 0.7 + intro_bonus * 0.3, 0.0, 1.0))


# ── Phase 15: Spectral Quality Scoring ───────────────────────────────────────

def _spectral_quality_score(
    mono: np.ndarray,
    sr: int,
    start: float,
    end: float,
) -> float:
    """
    Return a 0.0–1.0 quality score for a candidate window based on three
    spectral characteristics. Higher = cleaner-sounding window.

    Metrics
    -------
    crest_factor_score : Lower crest factor (less "peaky") → better-glued mix.
                         A fully compressed signal has crest ~ 0 dB; raw peaks
                         suggest the window catches a single loud transient.
                         Score = 1 − clip(crest_db / 40, 0, 1)

    centroid_stability : Low standard-deviation of spectral centroid across frames
                         → the tonal character is consistent, not wildly shifting.
                         Score = 1 − clip(centroid_std / 4000, 0, 1)

    harshness_score    : Lower ratio of 2–5 kHz energy to total energy → less
                         harsh / ear-fatiguing. Score = 1 − clip(ratio / 0.5, 0, 1)

    Final score is the mean of the three, computed on the mono slice only.
    Returns 0.5 on any error so it has no net effect on ranking.
    """
    try:
        s0 = max(0, int(round(start * sr)))
        s1 = min(mono.shape[0], int(round(end * sr)))
        if s1 <= s0 + sr // 10:          # window too short to analyse
            return 0.5

        chunk = mono[s0:s1]
        hop = 512
        n_fft = 2048

        # ── Crest factor ─────────────────────────────────────────────────────
        peak = float(np.abs(chunk).max()) + 1e-10
        rms  = float(np.sqrt(np.mean(chunk ** 2))) + 1e-10
        crest_db = 20.0 * np.log10(peak / rms)
        crest_score = float(1.0 - np.clip(crest_db / 40.0, 0.0, 1.0))

        # ── Spectral centroid stability ───────────────────────────────────────
        centroid = librosa.feature.spectral_centroid(y=chunk, sr=sr, n_fft=n_fft, hop_length=hop)[0]
        centroid_std = float(np.std(centroid))
        centroid_score = float(1.0 - np.clip(centroid_std / 4000.0, 0.0, 1.0))

        # ── Harshness ratio (2–5 kHz) ─────────────────────────────────────────
        stft = np.abs(librosa.stft(chunk, n_fft=n_fft, hop_length=hop))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
        harsh_mask = (freqs >= 2000) & (freqs <= 5000)
        total_energy  = float(stft.sum()) + 1e-10
        harsh_energy  = float(stft[harsh_mask, :].sum())
        harshness_ratio = harsh_energy / total_energy
        harshness_score = float(1.0 - np.clip(harshness_ratio / 0.5, 0.0, 1.0))

        score = (crest_score + centroid_score + harshness_score) / 3.0
        logger.debug(
            "_spectral_quality_score [%.2f–%.2f]s: crest=%.1fdB→%.2f "
            "centroid_std=%.0f→%.2f harshness=%.3f→%.2f  final=%.3f",
            start, end, crest_db, crest_score,
            centroid_std, centroid_score,
            harshness_ratio, harshness_score, score,
        )
        return round(float(np.clip(score, 0.0, 1.0)), 4)

    except Exception as exc:
        logger.warning("_spectral_quality_score failed at [%.2f–%.2f]s: %s", start, end, exc)
        return 0.5


# ── Phase 16: Intelligent Loop Helpers ───────────────────────────────────────

_REPEATABLE_LABELS = frozenset({"verse", "build", "chorus", "peak", "drop"})
_INTRO_LABELS      = frozenset({"intro"})
_OUTRO_LABELS      = frozenset({"outro", "bridge"})


def _build_arrangement(analysis: AnalysisResult, target_duration: float) -> list[int]:
    """
    Produce an ordered list of segment indices that, when concatenated, fill
    ``target_duration`` as closely as possible.

    Strategy
    --------
    1. Separate segments into intro, repeatable core (verse/build/chorus/peak/drop),
       and outro groups.
    2. If the core is empty or the track has fewer than 3 segments, fall back to
       repeating all segments in order.
    3. Repeat the core as many times as needed to cover ``target_duration``, then
       cap the last repetition at exactly what's still needed.

    Returns [] when the analysis has no segments (caller must fallback to tile loop).
    """
    segs = analysis.segments
    if not segs:
        return []

    intro_idxs     = [i for i, s in enumerate(segs) if s.label in _INTRO_LABELS]
    repeatable_idxs = [i for i, s in enumerate(segs) if s.label in _REPEATABLE_LABELS]
    outro_idxs     = [i for i, s in enumerate(segs) if s.label in _OUTRO_LABELS]

    def _dur(idx_list: list[int]) -> float:
        return sum(segs[i].end - segs[i].start for i in idx_list)

    # Need at least a repeatable core to do intelligent structuring
    if not repeatable_idxs or len(segs) < 3:
        # Fallback: repeat everything in order
        all_idxs = list(range(len(segs)))
        repeats = max(1, int(np.ceil(target_duration / max(analysis.duration, 0.1))))
        return all_idxs * repeats

    anchor_dur = _dur(intro_idxs) + _dur(outro_idxs)
    core_dur   = _dur(repeatable_idxs)
    fill_needed = max(0.0, target_duration - anchor_dur)
    n_repeats  = max(1, int(np.ceil(fill_needed / max(core_dur, 0.1))))

    arrangement = intro_idxs[:]
    for _ in range(n_repeats):
        arrangement.extend(repeatable_idxs)
    arrangement.extend(outro_idxs)

    logger.info(
        "_build_arrangement: intro=%s core=%s outro=%s repeats=%d → %d segments",
        intro_idxs, repeatable_idxs, outro_idxs, n_repeats, len(arrangement),
    )
    return arrangement


def _intelligent_loop(
    audio: np.ndarray,
    sr: int,
    analysis: AnalysisResult,
    target_duration: float,
    bpm: float = 120.0,
    crossfade_beats: float = 1.0,
    arrangement: Optional[list[int]] = None,
) -> np.ndarray:
    """
    Construct a looped output by intelligently repeating structural segments.

    Unlike ``_loop_to_target`` which tiles the entire source file, this function
    selects and orders segments musically (intro → verse → chorus … → outro),
    then crossfades between each junction using beat-synced envelopes.

    Falls back to ``_loop_to_target`` when:
    - The arrangement has fewer than 2 entries
    - Any segment slice is too short to crossfade

    Parameters
    ----------
    audio          : (channels, samples) float32 full source audio
    sr             : sample rate
    analysis       : structural analysis from ``analyze_audio``
    target_duration: desired total output in seconds
    bpm            : detected BPM for crossfade sizing
    crossfade_beats: crossfade length in beats at each junction
    arrangement    : explicit ordered segment indices (Phase 16 LLM override);
                     when None, computed via ``_build_arrangement``
    """
    if arrangement is None:
        arrangement = _build_arrangement(analysis, target_duration)

    target_samples = int(round(target_duration * sr))

    if len(arrangement) < 2:
        logger.info("_intelligent_loop: fallback (arrangement too short) → _loop_to_target")
        full_seg = audio[:, :int(round(analysis.duration * sr))]
        safe_bpm = max(bpm, 40.0)
        xfade_ms = float(np.clip(crossfade_beats * 60.0 / safe_bpm * 1000.0, 20.0, 500.0))
        return _loop_to_target(full_seg, sr, target_samples, xfade_ms=xfade_ms)

    # ── Compute beat-synced crossfade ─────────────────────────────────────────
    safe_bpm = max(bpm, 40.0)
    xfade_ms = float(np.clip(crossfade_beats * 60.0 / safe_bpm * 1000.0, 20.0, 500.0))
    xfade_n  = max(int(xfade_ms * sr / 1000), 1)

    segs = analysis.segments
    # Equal-power envelopes
    t_env = np.linspace(0.0, np.pi / 2.0, xfade_n, dtype=np.float32)
    fade_out_env = np.cos(t_env) ** 2
    fade_in_env  = np.sin(t_env) ** 2

    # ── Extract each segment slice ────────────────────────────────────────────
    slices: list[np.ndarray] = []
    for idx in arrangement:
        seg = segs[idx]
        s0 = max(0, int(round(seg.start * sr)))
        s1 = min(audio.shape[1], int(round(seg.end * sr)))
        chunk = audio[:, s0:s1].copy()
        if chunk.shape[1] > 0:
            slices.append(chunk)

    if not slices:
        logger.warning("_intelligent_loop: no valid slices — fallback")
        full_seg = audio[:, :int(round(analysis.duration * sr))]
        return _loop_to_target(full_seg, sr, target_samples, xfade_ms=xfade_ms)

    # ── Overlap-add stitch ────────────────────────────────────────────────────
    total_raw = sum(s.shape[1] for s in slices)
    # Keep repeating the arrangement until we exceed target
    all_slices = slices[:]
    while sum(s.shape[1] for s in all_slices) < target_samples + xfade_n:
        all_slices.extend(slices)

    # Allocate output buffer
    out_len = sum(s.shape[1] for s in all_slices)
    out = np.zeros((audio.shape[0], out_len), dtype=np.float32)

    pos = 0
    for j, chunk in enumerate(all_slices):
        cl = chunk.shape[1]
        end_pos = min(pos + cl, out_len)
        write_len = end_pos - pos

        c = chunk[:, :write_len].astype(np.float32)

        # Fade-out tail (except last chunk)
        if j < len(all_slices) - 1 and cl >= xfade_n:
            c[:, -xfade_n:] *= fade_out_env

        # Fade-in head (except first chunk)
        if j > 0:
            fi = min(xfade_n, write_len)
            c[:, :fi] *= fade_in_env[:fi]

        out[:, pos:end_pos] += c
        pos = end_pos
        if pos >= target_samples:
            break

    result = out[:, :target_samples]
    logger.info(
        "_intelligent_loop: %d slices stitched → %.3fs (target=%.3fs)",
        len(all_slices), result.shape[1] / sr, target_duration,
    )
    return result


# ── Phase 5: Editing Execution ────────────────────────────────────────────────

def execute_trim(
    audio: np.ndarray,
    sr: int,
    start_sec: float,
    end_sec: float,
    target_duration: Optional[float] = None,
    bpm: float = 120.0,
    crossfade_beats: float = 1.0,
    analysis: Optional["AnalysisResult"] = None,
    loop_arrangement: Optional[list[int]] = None,
) -> np.ndarray:
    """
    Slice audio to [start_sec, end_sec], loop-fill if target > segment, then
    apply a logarithmic outro fade over the last 1.5 seconds.

    Parameters
    ----------
    audio            : (channels, samples) float32 — original source array
    sr               : sample rate in Hz
    start_sec        : trim start in seconds (should be a downbeat)
    end_sec          : trim end in seconds (should be a downbeat)
    target_duration  : desired output length in seconds.
                       When ``target_duration > (end_sec - start_sec)`` the
                       trimmed segment is looped via overlap-add crossfade.
                       When ``None`` output length = segment length.
    bpm              : detected BPM — used to compute beat-synced crossfade length
    crossfade_beats  : crossfade duration expressed in beats (default 1 beat).
                       0.5 = half beat, 1 = one beat, 2 = two beats, 4 = one bar.
                       The crossfade is applied at all loop seams AND at the trim
                       start boundary (fade-in from silence over one crossfade window).
    analysis         : (Phase 16) when provided and needs_loop=True, enables intelligent
                       segment-aware loop restructuring instead of simple tiling.
    loop_arrangement : (Phase 16) explicit segment order from LLM arranger; passed
                       through to ``_intelligent_loop``.

    Returns
    -------
    np.ndarray  shape (channels, output_samples), float32

    Notes
    -----
    - Input array is never mutated; a copy is made before any modification.
    - Outro fade uses ``np.logspace(0, -4)`` — perceptually smooth fade-to-silence.
    - Loop crossfade uses equal-power (cos²/sin²) envelopes, beat-synced length.
    """
    # ── Beat-synced crossfade length ──────────────────────────────────────────
    safe_bpm = max(bpm, 40.0)
    beat_sec = 60.0 / safe_bpm
    xfade_ms = crossfade_beats * beat_sec * 1000.0   # ms
    # Clamp: never shorter than 20ms or longer than 500ms
    xfade_ms = float(np.clip(xfade_ms, 20.0, 500.0))
    logger.info(
        "execute_trim: bpm=%.1f crossfade_beats=%.1f → xfade=%.0fms",
        safe_bpm, crossfade_beats, xfade_ms,
    )

    # ── 1. Extract segment ────────────────────────────────────────────────────
    start_sample = int(round(start_sec * sr))
    end_sample = int(round(end_sec * sr))
    end_sample = min(end_sample, audio.shape[1])
    start_sample = max(0, min(start_sample, end_sample))

    segment = audio[:, start_sample:end_sample].copy()
    seg_samples = segment.shape[1]

    if seg_samples == 0:
        logger.warning("execute_trim: empty segment [%.2f–%.2f]s — returning silence", start_sec, end_sec)
        return segment

    seg_duration = seg_samples / sr
    logger.info(
        "execute_trim: sliced [%.2f–%.2f]s → %.3fs (%d samples)",
        start_sec, end_sec, seg_duration, seg_samples,
    )

    # ── 2. Fade-in at trim start boundary (beat-synced length) ───────────────
    # Smooths out abrupt entry if the cut landed between transients.
    fadein_samples = min(int(xfade_ms * sr / 1000), seg_samples // 4)
    fadein_samples = max(fadein_samples, 1)
    t_in = np.linspace(0.0, np.pi / 2.0, fadein_samples, dtype=np.float32)
    segment[:, :fadein_samples] *= np.sin(t_in) ** 2  # 0.0 → 1.0

    # ── 3. Loop-fill when target > segment ───────────────────────────────────
    if target_duration is not None and target_duration > seg_duration + 0.01:
        target_samples = int(round(target_duration * sr))

        if analysis is not None and len(analysis.segments) >= 3:
            # Phase 16: intelligent segment-aware restructuring
            logger.info("execute_trim: using _intelligent_loop (analysis available)")
            segment = _intelligent_loop(
                audio, sr, analysis, target_duration,
                bpm=safe_bpm, crossfade_beats=crossfade_beats,
                arrangement=loop_arrangement,
            )
        else:
            # Fallback: simple overlap-add tiling
            segment = _loop_to_target(segment, sr, target_samples, xfade_ms=xfade_ms)

        logger.info(
            "execute_trim: loop-fill %.3fs → %.3fs (%d samples)",
            seg_duration, segment.shape[1] / sr, segment.shape[1],
        )

    # ── 4. Logarithmic outro fade over last 1.5 s ─────────────────────────────
    fade_sec = 1.5
    fade_samples = min(int(fade_sec * sr), segment.shape[1])
    if fade_samples > 1:
        # np.logspace(0, -4, n): 10^0=1.0 → 10^-4=0.0001 — linear dB decay
        gain = np.logspace(0.0, -4.0, fade_samples, dtype=np.float32)
        segment[:, -fade_samples:] *= gain

    logger.info("execute_trim: output %.3fs (%d samples)", segment.shape[1] / sr, segment.shape[1])
    return segment.astype(np.float32)


def _loop_to_target(
    audio: np.ndarray,
    sr: int,
    target_samples: int,
    xfade_ms: float = 100.0,
) -> np.ndarray:
    """
    Repeat ``audio`` via overlap-add to reach ``target_samples``.

    Each copy advances by ``step = src_len - xfade_n`` samples.  At every
    seam the outgoing copy's tail (cos²-envelope fade-out) is added to the
    incoming copy's head (sin²-envelope fade-in), producing a click-free
    equal-power crossfade.

    Parameters
    ----------
    audio          : (channels, samples) float32 source segment
    sr             : sample rate
    target_samples : desired output length in samples
    xfade_ms       : crossfade duration in milliseconds (beat-synced from caller)
    """
    src_len = audio.shape[1]

    # Clamp crossfade to at most 25 % of source length
    xfade_n = min(int(xfade_ms * sr / 1000), src_len // 4)
    xfade_n = max(xfade_n, 1)

    step = max(src_len - xfade_n, 1)
    n_copies = (target_samples + step - 1) // step + 1

    # Pre-allocate output buffer (last copy may extend beyond target)
    out_len = (n_copies - 1) * step + src_len
    out = np.zeros((audio.shape[0], out_len), dtype=np.float32)

    # Equal-power (cos²/sin²) envelopes
    t = np.linspace(0.0, np.pi / 2.0, xfade_n, dtype=np.float32)
    fade_out_env = np.cos(t) ** 2   # 1.0 → 0.0
    fade_in_env = np.sin(t) ** 2    # 0.0 → 1.0

    for i in range(n_copies):
        pos = i * step
        if pos >= out_len:
            break

        copy_end = min(pos + src_len, out_len)
        copy_len = copy_end - pos
        copy = audio[:, :copy_len].astype(np.float32)

        # Apply fade-out to tail of every copy except the last
        if i < n_copies - 1 and copy_len == src_len:
            copy[:, -xfade_n:] *= fade_out_env

        # Apply fade-in to head of every copy except the first
        if i > 0:
            fi_len = min(xfade_n, copy_len)
            copy[:, :fi_len] *= fade_in_env[:fi_len]

        out[:, pos : pos + copy_len] += copy

    return out[:, :target_samples]
