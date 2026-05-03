import os
import sys
import shutil
import logging
import subprocess

from supabase_client import supabase

logger = logging.getLogger(__name__)

STORAGE_BUCKET = os.environ.get("BUCKET_NAME", "music-generated")
UPLOAD_DIR = "inputs"
OUTPUT_DIR = "outputs"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_separation_job(user_id: str, job_id: str) -> dict:
    logger.info("Fetching separation job: user_id=%s job_id=%s", user_id, job_id)
    response = (
        supabase.table("audio_separations")
        .select(
            "id, user_id, project_id, original_filename, status, "
            "vocals_url, drums_url, bass_url, other_url, error_message, created_at"
        )
        .eq("user_id", user_id)
        .eq("id", job_id)
        .execute()
    )

    rows = response.data or []
    if not rows:
        raise ValueError(f"No separation found for user_id={user_id} job_id={job_id}")
    return rows[0]


def _convert_to_wav(input_path: str) -> str:
    if input_path.lower().endswith(".wav"):
        return input_path
    output_path = input_path.rsplit(".", 1)[0] + ".wav"
    command = ["ffmpeg", "-y", "-i", input_path, "-ar", "44100", "-ac", "2", output_path]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path


def process_audio_background(job_id: str, input_path: str, user_id: str, project_id: str):
    wav_path = None
    output_folder = None
    try:
        supabase.table("audio_separations").update({"status": "IN_PROGRESS"}).eq("id", job_id).execute()
        logger.info("Job %s: status -> IN_PROGRESS", job_id)

        wav_path = _convert_to_wav(input_path)
        logger.info("Job %s: converted to WAV at %s", job_id, wav_path)

        # Compute output_folder before running demucs so the finally block
        # can clean up any partial output even if demucs fails mid-run
        base_name = os.path.splitext(os.path.basename(wav_path))[0]
        output_folder = os.path.join(OUTPUT_DIR, "htdemucs", base_name)

        command = [sys.executable, "-m", "demucs", "--segment", "10", "--out", OUTPUT_DIR, wav_path]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Demucs failed: {result.stderr}")
        logger.info("Job %s: demucs completed", job_id)

        stem_files = {
            "vocals": "vocals.wav",
            "drums": "drums.wav",
            "bass": "bass.wav",
            "other": "other.wav",
        }

        db_updates = {"status": "COMPLETED"}

        for stem_key, file_name in stem_files.items():
            local_file_path = os.path.join(output_folder, file_name)
            if not os.path.exists(local_file_path):
                raise Exception(f"Missing stem output: {file_name}")

            storage_path = f"{user_id}/{project_id}/{job_id}/{file_name}"
            with open(local_file_path, "rb") as f:
                supabase.storage.from_(STORAGE_BUCKET).upload(
                    file=f,
                    path=storage_path,
                    file_options={"content-type": "audio/wav"},
                )
            public_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(storage_path)
            db_updates[f"{stem_key}_url"] = public_url
            logger.info("Job %s: uploaded %s -> %s", job_id, stem_key, public_url)

        supabase.table("audio_separations").update(db_updates).eq("id", job_id).execute()
        logger.info("Job %s: status -> COMPLETED", job_id)

    except Exception as e:
        logger.error("Job %s failed: %s", job_id, e)
        supabase.table("audio_separations").update({
            "status": "FAILED",
            "error_message": str(e),
        }).eq("id", job_id).execute()

    finally:
        # Only delete this job's specific files — never remove the inputs/ or outputs/ folders
        try:
            if input_path and os.path.exists(input_path):
                os.remove(input_path)
                logger.info("Job %s: removed input file %s", job_id, input_path)
            if wav_path and wav_path != input_path and os.path.exists(wav_path):
                os.remove(wav_path)
                logger.info("Job %s: removed wav file %s", job_id, wav_path)
            if output_folder and os.path.exists(output_folder):
                shutil.rmtree(output_folder, ignore_errors=True)
                logger.info("Job %s: removed output folder %s", job_id, output_folder)
        except Exception as cleanup_err:
            logger.warning("Job %s: cleanup warning: %s", job_id, cleanup_err)
