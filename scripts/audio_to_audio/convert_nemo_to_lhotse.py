#!/usr/bin/env python
import argparse
import os

import numpy as np
from lhotse import AudioSource, CutSet, MonoCut, Recording
from lhotse.array import Array
from lhotse.audio import info
from lhotse.serialization import load_jsonl

from nemo.collections.common.parts.preprocessing.manifest import get_full_path

INPUT_CHANNEL_SELECTOR = "input_channel_selector"
TARGET_CHANNEL_SELECTOR = "target_channel_selector"
REFERENCE_CHANNEL_SELECTOR = "reference_channel_selector"
LHOTSE_TARGET_CHANNEL_SELECTOR = "target_recording_channel_selector"
LHOTSE_REFERENCE_CHANNEL_SELECTOR = "reference_recording_channel_selector"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert an audio-to-audio manifest from NeMo format to Lhotse format. "
        "This step enables the use of Lhotse datasets for audio-to-audio processing. "
    )
    parser.add_argument("input", help='Path to the input NeMo manifest.')
    parser.add_argument(
        "output", help="Path where we'll write the output Lhotse manifest (supported extensions: .jsonl.gz and .jsonl)"
    )
    parser.add_argument(
        "-i",
        "--input_key",
        default="audio_filepath",
        help="Key of the input recording, mapped to Lhotse's 'Cut.recording'.",
    )
    parser.add_argument(
        "-t",
        "--target_key",
        default="target_filepath",
        help="Key of the target recording, mapped to Lhotse's 'Cut.target_recording'.",
    )
    parser.add_argument(
        "-r",
        "--reference_key",
        default="reference_filepath",
        help="Key of the reference recording, mapped to Lhotse's 'Cut.reference_recording'.",
    )
    parser.add_argument(
        "-e",
        "--embedding_key",
        default="embedding_filepath",
        help="Key of the embedding, mapped to Lhotse's 'Cut.embedding_vector'.",
    )
    return parser.parse_args()


def create_recording(path_or_paths: str | list[str]) -> Recording:
    if isinstance(path_or_paths, list):
        cur_channel_idx = 0
        sources = []
        infos = []
        for p in path_or_paths:
            i = info(p)
            infos.append(i)
            sources.append(
                AudioSource(type="file", channels=list(range(cur_channel_idx, cur_channel_idx + i.channels)), source=p)
            )
            cur_channel_idx += i.channels
        assert all(
            i.samplerate == infos[0].samplerate for i in infos[1:]
        ), f"Mismatched sampling rates for individual audio files in: {path_or_paths}"
        recording = Recording(
            id=p[0],
            sources=sources,
            sampling_rate=infos[0].samplerate,
            num_samples=infos[0].frames,
            duration=infos[0].duration,
            channel_ids=list(range(0, cur_channel_idx)),
        )
    else:
        recording = Recording.from_file(path_or_paths)
    return recording


def create_array(path: str) -> Array:
    assert path.endswith(".npy"), f"Currently only conversion of numpy files is supported (got: {path})"
    arr = np.load(path)
    parent, path = os.path.split(path)
    return Array(storage_type="numpy_files", storage_path=parent, storage_key=path, shape=list(arr.shape),)


def main():
    args = parse_args()
    with CutSet.open_writer(args.output) as writer:
        for item in load_jsonl(args.input):

            # Create Lhotse recording and cut object, apply offset and duration slicing if present.
            recording = create_recording(get_full_path(audio_file=item.pop(args.input_key), manifest_file=args.input))
            cut = recording.to_cut().truncate(duration=item.pop("duration"), offset=item.pop("offset", 0.0))

            if (channels := item.pop(INPUT_CHANNEL_SELECTOR, None)) is not None:
                if cut.num_channels == 1:
                    assert (
                        len(channels) == 1
                    ), f"The input recording has only a single channel, but manifest specified {INPUT_CHANNEL_SELECTOR}={channels}"
                else:
                    cut = cut.with_channels(channels)

            if args.target_key in item:
                cut.target_recording = create_recording(
                    get_full_path(audio_file=item.pop(args.target_key), manifest_file=args.input)
                )
                if (channels := item.pop(TARGET_CHANNEL_SELECTOR, None)) is not None:
                    if cut.target_recording.num_channels == 1:
                        assert (
                            len(channels) == 1
                        ), f"The target recording has only a single channel, but manifest specified {TARGET_CHANNEL_SELECTOR}={channels}"
                    else:
                        cut = cut.with_custom(LHOTSE_TARGET_CHANNEL_SELECTOR, channels)

            if args.reference_key in item:
                cut.reference_recording = create_recording(
                    get_full_path(audio_file=item.pop(args.reference_key), manifest_file=args.input)
                )
                if (channels := item.pop(REFERENCE_CHANNEL_SELECTOR, None)) is not None:
                    if cut.reference_recording.num_channels == 1:
                        assert (
                            len(channels) == 1
                        ), f"The reference recording has only a single channel, but manifest specified {REFERENCE_CHANNEL_SELECTOR}={channels}"
                    else:
                        cut = cut.with_custom(LHOTSE_REFERENCE_CHANNEL_SELECTOR, channels)

            if args.embedding_key in item:
                cut.embedding_vector = create_array(
                    get_full_path(audio_file=item.pop(args.embedding_key), manifest_file=args.input)
                )

            if item:
                cut.custom.update(item)  # any field that's still left goes to custom fields

            writer.write(cut)


if __name__ == "__main__":
    main()