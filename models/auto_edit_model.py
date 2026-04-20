from pydantic import BaseModel, Field
from typing import List, Optional


class SegmentInfo(BaseModel):
    start: float = Field(..., description="Segment start time in seconds")
    end: float = Field(..., description="Segment end time in seconds")
    energy: float = Field(..., description="RMS energy of this segment (0.0–1.0 normalised)")
    label: str = Field(..., description="Heuristic label: intro | build | peak | outro")


class CandidateWindow(BaseModel):
    """A scored candidate trim window, returned in both /analyze and /trim responses."""
    index: int = Field(..., description="Rank index (0 = highest-scoring)")
    start: float = Field(..., description="Window start in seconds (snapped to downbeat)")
    end: float = Field(..., description="Window end in seconds (snapped to downbeat)")
    duration: float = Field(..., description="Window duration in seconds")
    duration_score: float = Field(..., description="0.0–1.0: closeness to target_duration")
    energy_score: float = Field(..., description="0.0–1.0: energy preference match")
    structural_score: float = Field(..., description="0.0–1.0: fraction of segments fully covered")
    spectral_quality_score: float = Field(0.5, description="0.0–1.0: audio quality (crest, centroid stability, harshness)")
    total_score: float = Field(..., description="Weighted total used for ranking")
    segment_labels: List[str] = Field(..., description="Labels of segments overlapping this window")
    needs_loop: bool = Field(False, description="True when target > source; execute_trim will loop")


class AudioAnalysis(BaseModel):
    bpm: float = Field(..., description="Detected tempo in BPM")
    duration: float = Field(..., description="Total source duration in seconds")
    beat_times: List[float] = Field(..., description="Beat timestamps in seconds")
    downbeat_times: List[float] = Field(..., description="Downbeat timestamps (bar '1') in seconds")
    segments: List[SegmentInfo] = Field(..., description="Structural segments with energy and label")
    candidates: Optional[List[CandidateWindow]] = Field(
        None,
        description="Candidate windows — only present when target_duration is passed to /analyze",
    )


class AutoTrimRequest(BaseModel):
    """Form-data params for POST /auto-edit/trim."""
    target_duration: float = Field(..., gt=0, description="Desired output duration in seconds")
    energy_preference: Optional[str] = Field(
        None,
        description="Optional energy bias: high_energy | climax | intro_heavy",
    )
    output_format: str = Field("mp3", description="Output format: mp3 or wav")
    chosen_window_index: Optional[int] = Field(
        None,
        ge=0,
        description="When set, skip LLM and use this candidate index directly (0 = best-scored)",
    )
    strictness: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description=(
            "0.0 = Musical (prioritise best-sounding window regardless of duration deviation); "
            "1.0 = Precise (hit target duration exactly, even if cut lands mid-phrase). "
            "Default 0.5 = balanced."
        ),
    )
    crossfade_beats: float = Field(
        1.0,
        description=(
            "Crossfade length at loop seams and trim boundaries, expressed in beats. "
            "0.5 = half beat, 1 = one beat (default), 2 = two beats, 4 = one bar."
        ),
    )


class AutoTrimResponse(BaseModel):
    """Full JSON response from POST /auto-edit/trim."""
    # Audio payload
    audio_b64: str = Field(..., description="Base64-encoded audio bytes")
    audio_format: str = Field(..., description="Audio format: mp3 or wav")
    # Chosen window
    chosen_index: int = Field(..., description="Index of the chosen candidate (0-based)")
    window_start: float = Field(..., description="Trim start in seconds")
    window_end: float = Field(..., description="Trim end in seconds")
    actual_duration: float = Field(..., description="Actual output duration after beat-snapping")
    # Quality metrics
    bpm: float = Field(..., description="Detected BPM")
    beat_deviation_ms: float = Field(..., description="Cut-point deviation from nearest beat in ms")
    was_looped: bool = Field(..., description="True if source was looped to fill target")
    used_fallback: bool = Field(..., description="True if LLM selection failed and rank-0 was used")
    agent_reasoning: Optional[str] = Field(None, description="LLM reasoning for window choice")
    quality_warning: Optional[str] = Field(None, description="Non-empty when looping ratio is high or click detected")
    # All candidates for UI comparison
    candidates: List[CandidateWindow] = Field(..., description="All scored candidate windows, ranked by total_score")
