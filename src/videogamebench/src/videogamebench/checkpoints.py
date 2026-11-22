"""Extract reviewed walkthrough frames and audit them with upstream's image hash.

The plan is data: video names, timestamps, normalized crops, milestone labels,
provenance and review status. This utility never modifies upstream checkpoints.
"""

import argparse
import hashlib
import html
import io
import json
import math
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any


def safe_name(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
        raise ValueError(f"Unsafe identifier: {value!r}")
    return value


def crop_box(crop, size):
    if len(crop) != 4 or any(not math.isfinite(v) for v in crop):
        raise ValueError("Crop must contain four finite normalized coordinates")
    left, top, right, bottom = crop
    if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
        raise ValueError("Crop must be a nonempty rectangle within [0, 1]")
    width, height = size
    box = tuple(round(v * s) for v, s in zip(crop, (width, height, width, height)))
    if box[0] == box[2] or box[1] == box[3]:
        raise ValueError("Crop is smaller than one pixel")
    return box


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def generate(
    plan, video_dir, source_dir, output_dir, ffmpeg, overwrite=False, progress_every=10
):
    import imagehash
    from PIL import Image

    entries = plan["checkpoints"]
    identifiers = set()
    for entry in entries:
        key = tuple(safe_name(str(entry[k])) for k in ("profile", "game", "id"))
        if key in identifiers:
            raise ValueError(f"Duplicate checkpoint: {key}")
        identifiers.add(key)
        timestamp = entry["timestamp_sec"]
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("Timestamp must be finite and nonnegative")
        crop_box(entry.get("crop", [0, 0, 1, 1]), (10000, 10000))
        safe_name(entry["video"])
        video = video_dir / f"{entry['video']}.video.mp4"
        if not video.is_file():
            raise FileNotFoundError(video)
        if entry.get("upstream_id") is not None:
            reference = (
                source_dir
                / "configs"
                / entry["game"]
                / "checkpoints"
                / f"{int(entry['upstream_id'])}.png"
            )
            if not reference.is_file():
                raise FileNotFoundError(reference)
            expected_reference = entry.get("upstream_sha256")
            if expected_reference and digest(reference) != expected_reference:
                raise ValueError(f"Published reference content changed: {reference}")
        target = output_dir.joinpath(*key).with_suffix(".png")
        if target.exists() and not overwrite:
            raise FileExistsError(f"{target}; use --overwrite to regenerate")

    video_digests = {}
    for name in sorted({entry["video"] for entry in entries}):
        actual = digest(video_dir / f"{name}.video.mp4")
        expected = plan["videos"][name].get("sha256")
        if expected and actual != expected:
            raise ValueError(
                f"Video content changed for {name}; review the source and timestamps"
            )
        video_digests[name] = actual
    results: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, 1):
        video = video_dir / f"{entry['video']}.video.mp4"
        if entry["video"] not in video_digests:
            video_digests[entry["video"]] = digest(video)
        relative = Path(entry["profile"]) / entry["game"] / f"{entry['id']}.png"
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        command = [
            ffmpeg,
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            str(entry["timestamp_sec"]),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ]
        process = subprocess.run(command, check=True, capture_output=True)
        with Image.open(io.BytesIO(process.stdout)) as frame:
            source_size = frame.size
            box = crop_box(entry.get("crop", [0, 0, 1, 1]), source_size)
            cropped = frame.crop(box).convert("RGB")
            cropped.save(target)
            frame_hash = imagehash.average_hash(cropped)
        result: dict[str, Any] = {
            **entry,
            "path": relative.as_posix(),
            "sha256": digest(target),
            "average_hash": str(frame_hash),
            "source_size": list(source_size),
            "crop_px": list(box),
            "video_sha256": video_digests[entry["video"]],
        }
        reference_id = entry.get("upstream_id")
        if reference_id is not None:
            reference = (
                source_dir
                / "configs"
                / entry["game"]
                / "checkpoints"
                / f"{int(reference_id)}.png"
            )
            with Image.open(reference) as ref:
                ref_hash = imagehash.average_hash(ref)
            distance = int(frame_hash - ref_hash)
            threshold = entry.get("threshold", plan.get("threshold", 10))
            reference_relative = (
                Path("published") / entry["game"] / f"{int(reference_id)}.png"
            )
            reference_target = output_dir / reference_relative
            reference_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(reference, reference_target)
            result["comparison"] = {
                "reference_path": reference_relative.as_posix(),
                "reference_sha256": digest(reference),
                "reference_hash": str(ref_hash),
                "distance": distance,
                "threshold": threshold,
                "within_threshold": distance <= threshold,
            }
        results.append(result)
        if index == 1 or index == len(entries) or index % progress_every == 0:
            print(
                f"[{index}/{len(entries)}] {relative} "
                f"{result.get('comparison', {}).get('distance', '-')} "
                f"{entry.get('review_status', 'unreviewed')}",
                flush=True,
            )
    report = {
        "schema_version": 1,
        "upstream_revision": plan["upstream_revision"],
        "hash_algorithm": "imagehash.average_hash(hash_size=8)",
        "note": "Hash agreement is not emulator compatibility or proof of milestone completion.",
        "videos": plan["videos"],
        "checkpoints": results,
        "hash_ambiguities": hash_ambiguities(results, plan.get("threshold", 10)),
        "published_hash_ambiguities": hash_ambiguities(
            [
                {**entry, "average_hash": entry["comparison"]["reference_hash"]}
                for entry in results
                if "comparison" in entry
            ],
            plan.get("threshold", 10),
        ),
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    write_gallery(report, output_dir)
    return report


def write_gallery(report, output_dir):
    cards = []
    for result in report["checkpoints"]:
        label = (
            f"{result['profile']}/{result['game']}/{result['id']}: {result['label']}"
        )
        comparison = result.get("comparison", {})
        published = ""
        if "reference_path" in comparison:
            published = f"<figure><img loading='lazy' src='{html.escape(comparison['reference_path'], quote=True)}'><figcaption>Published reference</figcaption></figure>"
        url = report["videos"][result["video"]].get("webpage_url", "")
        source_link = f"{url}&t={int(result['timestamp_sec'])}s"
        cards.append(
            f"<article data-game='{result['game']}' data-profile='{result['profile']}'>"
            f"<h3>{html.escape(label)}</h3><div class='images'>{published}"
            f"<figure><img loading='lazy' src='{html.escape(result['path'], quote=True)}'>"
            "<figcaption>Regenerated frame</figcaption></figure></div>"
            f"<p>{html.escape(result.get('review_status', 'unreviewed'))}; "
            f"t={result['timestamp_sec']}s; hash distance={comparison.get('distance', 'n/a')}</p>"
            f"<p>{html.escape(result.get('notes', ''))}</p>"
            f"<a href='{html.escape(source_link, quote=True)}' target='_blank' rel='noreferrer'>Walkthrough at this checkpoint</a></article>"
        )
    games = sorted({entry["game"] for entry in report["checkpoints"]})
    profiles = sorted({entry["profile"] for entry in report["checkpoints"]})

    def select(name, values):
        return (
            f"<label>{name} <select id='{name}'><option value=''>All</option>"
            + "".join(f"<option>{html.escape(value)}</option>" for value in values)
            + "</select></label>"
        )

    comparisons = [
        entry["comparison"] for entry in report["checkpoints"] if "comparison" in entry
    ]
    matches = sum(entry["within_threshold"] for entry in comparisons)
    document = (
        "<!doctype html><meta charset='utf-8'><title>VideoGameBench checkpoint audit</title>"
        "<style>body{font:16px sans-serif;background:#eee;margin:20px}main{display:grid;grid-template-columns:"
        "repeat(auto-fit,minmax(450px,1fr));gap:12px}article{background:white;padding:12px}"
        "article[hidden]{display:none}.images{display:flex;gap:8px}figure{margin:0;flex:1;min-width:0}"
        "img{width:100%;height:240px;object-fit:contain}label{margin-right:16px}header{position:sticky;top:0;background:#eee;padding:10px}</style>"
        "<header><h1>Checkpoint audit</h1>"
        f"<p>{len(report['checkpoints'])} extracted frames; {matches}/{len(comparisons)} published references match their thresholds.</p>"
        "<p>Expanded references require emulator validation. Hash agreement alone does not prove a unique milestone.</p>"
        + select("game", games)
        + select("profile", profiles)
        + "<label>Search <input id='search'></label></header><main>"
        + "".join(cards)
        + "</main>"
        + "<script>function filter(){let g=document.querySelector('#game').value,p=document.querySelector('#profile').value,q=document.querySelector('#search').value.toLowerCase();document.querySelectorAll('article').forEach(a=>a.hidden=!!((g&&a.dataset.game!==g)||(p&&a.dataset.profile!==p)||(q&&!a.textContent.toLowerCase().includes(q))))}document.querySelectorAll('select,input').forEach(e=>e.addEventListener('input',filter));</script>"
    )
    (output_dir / "index.html").write_text(document)


def hash_ambiguities(entries, default_threshold=10):
    """Find checkpoint pairs that the unmodified upstream matcher conflates."""
    groups = defaultdict(list)
    for entry in entries:
        groups[(entry["profile"], entry["game"])].append(entry)
    pairs = []
    for (profile, game), group in groups.items():
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                distance = (
                    int(left["average_hash"], 16) ^ int(right["average_hash"], 16)
                ).bit_count()
                threshold = right.get("threshold", default_threshold)
                if distance <= threshold:
                    pairs.append(
                        {
                            "profile": profile,
                            "game": game,
                            "left": left["id"],
                            "right": right["id"],
                            "distance": distance,
                            "threshold": threshold,
                            "includes_final": bool(
                                left.get("final") or right.get("final")
                            ),
                        }
                    )
    return pairs


def download_missing(
    plan, video_dir, *, workers=8, chunk_bytes=1048576, retries=3, timeout=30
):
    """Download exact planned formats without storing expiring signed URLs."""
    import concurrent.futures
    import threading
    import time
    import urllib.request

    import yt_dlp

    video_dir.mkdir(parents=True, exist_ok=True)
    for name in sorted({entry["video"] for entry in plan["checkpoints"]}):
        safe_name(name)
        target = video_dir / f"{name}.video.mp4"
        if target.exists():
            continue
        source = plan["videos"][name]
        with yt_dlp.YoutubeDL(
            {"quiet": True, "skip_download": True, "socket_timeout": timeout}
        ) as downloader:
            info = downloader.extract_info(source["webpage_url"], download=False)
        selected = next(
            (
                item
                for item in info["formats"]
                if item["format_id"] == source["format_id"]
            ),
            None,
        )
        if (
            selected is None
            or selected.get("protocol") != "https"
            or not selected.get("filesize")
        ):
            raise ValueError(
                f"The planned direct HTTPS format is unavailable for {name}; review the source before changing the plan"
            )
        size = selected["filesize"]
        partial = target.with_suffix(".part")
        lock = threading.Lock()
        with partial.open("w+b") as stream:
            stream.truncate(size)

            def fetch(
                start,
                size=size,
                selected=selected,
                info=info,
                lock=lock,
                stream=stream,
                name=name,
            ):
                end = min(start + chunk_bytes, size) - 1
                for attempt in range(retries):
                    try:
                        request = urllib.request.Request(
                            selected["url"] + f"&range={start}-{end}",
                            headers=info.get("http_headers", {}),
                        )
                        with urllib.request.urlopen(
                            request, timeout=timeout
                        ) as response:
                            data = response.read(end - start + 2)
                        if len(data) != end - start + 1:
                            raise ValueError("Unexpected range response size")
                        with lock:
                            stream.seek(start)
                            stream.write(data)
                        return
                    except (OSError, ValueError) as error:
                        if attempt + 1 == retries:
                            raise RuntimeError(
                                f"Download failed for {name}: {type(error).__name__}"
                            ) from None
                        time.sleep(attempt + 1)

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(fetch, range(0, size, chunk_bytes)))
        expected = source.get("sha256")
        if expected and digest(partial) != expected:
            raise ValueError(
                f"Video content changed for {name}; review the source and timestamps"
            )
        partial.replace(target)
        print(f"Downloaded {name}: {size} bytes", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--video-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--ffmpeg", help="Decoder executable; defaults to imageio-ffmpeg's binary"
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--download-missing", action="store_true")
    parser.add_argument("--download-workers", type=int, default=8)
    parser.add_argument("--download-chunk-bytes", type=int, default=1048576)
    parser.add_argument("--download-retries", type=int, default=3)
    parser.add_argument("--download-timeout", type=float, default=30)
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--strict-reference-matches", action="store_true")
    args = parser.parse_args()
    for name in (
        "download_workers",
        "download_chunk_bytes",
        "download_retries",
        "download_timeout",
        "progress_every",
    ):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive and finite")
    plan = json.loads(args.plan.read_text())
    if args.download_missing:
        download_missing(
            plan,
            args.video_dir,
            workers=args.download_workers,
            chunk_bytes=args.download_chunk_bytes,
            retries=args.download_retries,
            timeout=args.download_timeout,
        )
    if args.ffmpeg is None:
        import imageio_ffmpeg

        args.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    report = generate(
        plan,
        args.video_dir,
        args.source_dir,
        args.output_dir,
        args.ffmpeg,
        args.overwrite,
        args.progress_every,
    )
    comparisons = [
        entry["comparison"] for entry in report["checkpoints"] if "comparison" in entry
    ]
    failures = sum(not comparison["within_threshold"] for comparison in comparisons)
    print(
        f"Extracted {len(report['checkpoints'])} frames; reference mismatches: {failures}/{len(comparisons)}"
    )
    if args.strict_reference_matches and failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
