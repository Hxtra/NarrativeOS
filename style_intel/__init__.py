"""NarrativeOS Style Intelligence: measure a reference video's editing language as Style DNA.

    python -m style_intel analyze <video> --out <dir>
    python -m style_intel profile <dir>/style_dna.json --id <style_id>

Every Style DNA value is measured from the video (ffmpeg, OpenCV, librosa,
faster-whisper). Anything that cannot be measured yet is reported with
status "not_measured" and a reason, never guessed.
"""

ANALYZER_VERSION = "0.1.0"
