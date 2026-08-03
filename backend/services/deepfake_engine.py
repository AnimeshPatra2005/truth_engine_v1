"""
Deepfake Detection Engine

Loads the ms-eff-gcvit-deepfake-b0-ff-plus-plus model at container startup
and provides frame-level deepfake detection with time-range segment localization.

Model: KoreaPeter/ms-eff-gcvit-deepfake-b0-ff-plus-plus
Architecture: Multi-Scale Efficient Global Context Vision Transformer (b0 variant)
Input: Video file (face-level, frame-by-frame)
Output: Per-frame fake probability scores, aggregated label, segment timestamps
"""

import os
import time
from typing import List, Dict, Any, Optional

# Module-level pipeline cache — loaded once at startup, reused on every request
_pipeline = None

NUM_FRAMES = 20  # Frames sampled per video (model default is 20)


# ---------------------------------------------------------------------------
# Startup loader
# ---------------------------------------------------------------------------

def load_deepfake_model() -> None:
    """
    Load the deepfake detection pipeline into module-level cache.
    Must be called once at application startup via FastAPI lifespan.
    Downloads model weights from HuggingFace Hub on first run (~36MB).
    """
    global _pipeline
    print("Loading deepfake detection model (ms-eff-gcvit-b0)...")
    start = time.time()

    try:
        from transformers import pipeline as hf_pipeline

        _pipeline = hf_pipeline(
            "video-classification",
            model="KoreaPeter/ms-eff-gcvit-deepfake-b0-ff-plus-plus",
            trust_remote_code=True,
        )
        elapsed = time.time() - start
        print(f"Deepfake model ready in {elapsed:.1f}s")

    except Exception as e:
        print(f"WARNING: Deepfake model failed to load — detection will be unavailable. Error: {e}")
        _pipeline = None


# ---------------------------------------------------------------------------
# Video duration helper
# ---------------------------------------------------------------------------

def _get_video_duration(video_path: str) -> float:
    """
    Return video duration in seconds using OpenCV.
    Returns 0.0 on failure (e.g., audio-only files).
    """
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        if fps > 0 and frame_count > 0:
            return frame_count / fps
        return 0.0
    except Exception as e:
        print(f"Could not determine video duration: {e}")
        return 0.0


# ---------------------------------------------------------------------------
# Segment detection
# ---------------------------------------------------------------------------

def _detect_fake_segments(
    frame_scores: List[float],
    video_path: str,
    num_frames: int,
    block_size: int = 4,
    vote_thresh: int = 3,
    score_thresh: float = 0.5,
) -> List[Dict[str, Any]]:
    """
    Convert a flat list of per-frame fake-probability scores into a list of
    contiguous time segments where the video is likely manipulated.

    Algorithm:
      1. Group frames into blocks of `block_size`.
      2. A block is flagged fake if at least `vote_thresh` frames in the block
         exceed `score_thresh`.
      3. Consecutive fake blocks are merged into a single segment.
      4. Average confidence for each segment is the mean of per-frame scores
         that were above threshold within that segment.

    Returns:
        List of {"start": float, "end": float, "confidence": float}
        Start/end are in seconds. Confidence is in [0, 1].
    """
    duration = _get_video_duration(video_path)
    if duration <= 0.0 or not frame_scores:
        return []

    seconds_per_frame = duration / num_frames

    # --- Step 1: Block-level majority vote ---
    block_flags = []
    for start_idx in range(0, len(frame_scores), block_size):
        block = frame_scores[start_idx: start_idx + block_size]
        fake_votes = [s for s in block if s >= score_thresh]
        is_fake_block = len(fake_votes) >= vote_thresh

        # Average of scores that voted "fake" in this block
        block_confidence = (
            sum(fake_votes) / len(fake_votes) if fake_votes else 0.0
        )

        block_start = start_idx * seconds_per_frame
        block_end = min((start_idx + len(block)) * seconds_per_frame, duration)
        block_flags.append((block_start, block_end, is_fake_block, block_confidence))

    # --- Step 2: Merge consecutive fake blocks ---
    segments = []
    current_start: Optional[float] = None
    current_confidences: List[float] = []
    last_end = 0.0

    for block_start, block_end, is_fake, conf in block_flags:
        if is_fake and current_start is None:
            current_start = block_start
            current_confidences = [conf]
        elif is_fake and current_start is not None:
            current_confidences.append(conf)
        elif not is_fake and current_start is not None:
            segments.append({
                "start": round(current_start, 2),
                "end": round(last_end, 2),
                "confidence": round(
                    sum(current_confidences) / len(current_confidences), 4
                ),
            })
            current_start = None
            current_confidences = []
        last_end = block_end

    # Close any segment still open at the end of the video
    if current_start is not None and current_confidences:
        segments.append({
            "start": round(current_start, 2),
            "end": round(last_end, 2),
            "confidence": round(
                sum(current_confidences) / len(current_confidences), 4
            ),
        })

    return segments


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_deepfake_detection(video_path: str) -> Dict[str, Any]:
    """
    Run the deepfake detection pipeline on a local video file.

    Args:
        video_path: Absolute path to a video file already saved on disk.

    Returns:
        {
            "is_fake":        bool,
            "label":          "fake" | "real" | "unknown",
            "overall_score":  float,  # probability the video is fake, 0–1
            "segments":       [{"start": float, "end": float, "confidence": float}],
            "error":          bool,
            "error_message":  str | None
        }
    """
    if _pipeline is None:
        return {
            "is_fake": False,
            "label": "unknown",
            "overall_score": 0.0,
            "segments": [],
            "error": True,
            "error_message": "Deepfake model unavailable (failed to load at startup).",
        }

    print(f"Running deepfake detection on: {os.path.basename(video_path)}")
    start = time.time()

    duration = _get_video_duration(video_path)
    # Target ~1 frame per second to ensure high accuracy on long videos,
    # bounded between 20 (minimum) and 120 (maximum to prevent memory OOM)
    dynamic_frames = max(20, min(120, int(duration))) if duration > 0 else NUM_FRAMES
    print(f"Video duration: {duration:.1f}s, sampling {dynamic_frames} frames.")

    try:
        raw_result = _pipeline(
            video_path,
            num_frames=dynamic_frames,
            return_frame_scores=True,
        )

        # The pipeline returns a list:
        # [{"label": "fake", "score": 0.96},
        #  {"label": "real", "score": 0.04},
        #  {"frame_scores": [...], "agg_mode": "conf"}]

        fake_entry = next(
            (r for r in raw_result if r.get("label") == "fake"), None
        )
        frame_scores_entry = next(
            (r for r in raw_result if "frame_scores" in r), None
        )

        overall_fake_score: float = fake_entry["score"] if fake_entry else 0.0
        frame_scores: List[float] = (
            frame_scores_entry["frame_scores"] if frame_scores_entry else []
        )

        is_fake = overall_fake_score >= 0.5
        label = "fake" if is_fake else "real"

        # Segment detection only makes sense for video files when fake
        segments: List[Dict] = []
        video_extensions = {".mp4", ".webm", ".avi", ".mov", ".mkv"}
        if is_fake and frame_scores and os.path.splitext(video_path)[1].lower() in video_extensions:
            # We must pass the dynamic_frames we actually used!
            segments = _detect_fake_segments(frame_scores, video_path, dynamic_frames)

        elapsed = time.time() - start
        print(
            f"Deepfake detection done in {elapsed:.1f}s — "
            f"label={label}, score={overall_fake_score:.4f}, segments={len(segments)}"
        )

        return {
            "is_fake": is_fake,
            "label": label,
            "overall_score": round(overall_fake_score, 4),
            "segments": segments,
            "error": False,
            "error_message": None,
        }

    except Exception as e:
        print(f"Deepfake detection failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "is_fake": False,
            "label": "unknown",
            "overall_score": 0.0,
            "segments": [],
            "error": True,
            "error_message": str(e),
        }
