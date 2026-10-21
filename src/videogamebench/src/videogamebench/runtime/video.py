"""Bounded-memory observation video recording, independent of any host display."""

import io
import json
import threading
import time
from pathlib import Path


class ObservationVideo:
    def __init__(self, directory: Path, fps: float):
        self.directory, self.fps = directory, fps
        self.latest = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.error = None

    def update(self, image: bytes):
        with self.lock:
            self.latest = (image, time.monotonic())
            if self.thread is None:
                self.thread = threading.Thread(target=self.record, daemon=True)
                self.thread.start()

    def record(self):
        writer = None
        started = time.monotonic()
        index = 0
        try:
            import cv2
            import numpy as np
            from PIL import Image

            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / "video-timestamps.jsonl").open("w") as timestamps:
                while True:
                    with self.lock:
                        screen, observed_at = self.latest
                    with Image.open(io.BytesIO(screen)) as image:
                        frame = cv2.cvtColor(
                            np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR
                        )
                    if writer is None:
                        height, width = frame.shape[:2]
                        writer = cv2.VideoWriter(
                            str(self.directory / "gameplay.mp4"),
                            cv2.VideoWriter_fourcc(*"mp4v"),
                            self.fps,
                            (width, height),
                        )
                        if not writer.isOpened():
                            raise RuntimeError(
                                "Could not initialize MP4 observation recorder"
                            )
                    writer.write(frame)
                    timestamps.write(
                        json.dumps(
                            {
                                "frame": index,
                                "recorded_elapsed_sec": time.monotonic() - started,
                                "observation_elapsed_sec": max(
                                    0, observed_at - started
                                ),
                            }
                        )
                        + "\n"
                    )
                    index += 1
                    if self.stop_event.wait(
                        max(0, started + index / self.fps - time.monotonic())
                    ):
                        break
        except Exception as exc:  # noqa: BLE001 -- retain recording failures without falsifying game scores
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            if writer is not None:
                writer.release()

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=30)
            if self.thread.is_alive():
                self.error = "Video finalization timed out"
