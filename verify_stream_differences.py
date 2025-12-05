#!/usr/bin/env python3
"""
Verify if multiple stream_ids for the same episode are actually different
(resolution, bitrate, codec, etc.) or just duplicates.

This uses ffprobe to analyze the actual streams.
"""

import subprocess
import json
import logging

logger = logging.getLogger(__name__)

def ffprobe_stream(url, timeout=10):
    """
    Use ffprobe to get stream metadata.

    Returns dict with:
    - resolution: "1920x1080"
    - bitrate: 5000000 (bits per second)
    - codec: "h264"
    - duration: 3600 (seconds)
    - audio_codec: "aac"
    - audio_bitrate: 128000
    """
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            '-analyzeduration', '5000000',  # 5 seconds
            '-probesize', '10000000',       # 10MB
            url
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode != 0:
            logger.error(f"ffprobe failed: {result.stderr}")
            return None

        data = json.loads(result.stdout)

        # Extract video stream info
        video_stream = None
        audio_stream = None

        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video' and not video_stream:
                video_stream = stream
            elif stream.get('codec_type') == 'audio' and not audio_stream:
                audio_stream = stream

        if not video_stream:
            logger.warning("No video stream found")
            return None

        metadata = {
            'resolution': f"{video_stream.get('width', 0)}x{video_stream.get('height', 0)}",
            'width': video_stream.get('width', 0),
            'height': video_stream.get('height', 0),
            'codec': video_stream.get('codec_name', 'unknown'),
            'bitrate': int(data.get('format', {}).get('bit_rate', 0)),
            'duration': float(data.get('format', {}).get('duration', 0)),
            'fps': eval(video_stream.get('r_frame_rate', '0/1')),
        }

        if audio_stream:
            metadata['audio_codec'] = audio_stream.get('codec_name', 'unknown')
            metadata['audio_channels'] = audio_stream.get('channels', 0)

        return metadata

    except subprocess.TimeoutExpired:
        logger.error(f"ffprobe timeout after {timeout}s")
        return None
    except Exception as e:
        logger.error(f"ffprobe error: {e}")
        return None


def compare_streams(stream_urls, stream_ids):
    """
    Compare multiple stream URLs to see if they're actually different.

    Args:
        stream_urls: List of URLs to compare
        stream_ids: List of stream IDs (for labeling)

    Returns:
        dict: Comparison results
    """
    print("=" * 80)
    print("Stream Analysis and Comparison")
    print("=" * 80)

    results = {}

    for stream_id, url in zip(stream_ids, stream_urls):
        print(f"\nAnalyzing stream {stream_id}...")
        print(f"URL: {url}")

        metadata = ffprobe_stream(url)

        if metadata:
            results[stream_id] = metadata
            print(f"  Resolution: {metadata['resolution']}")
            print(f"  Codec: {metadata['codec']}")
            print(f"  Bitrate: {metadata['bitrate'] / 1000:.0f} kbps")
            print(f"  FPS: {metadata['fps']:.2f}")
            print(f"  Duration: {metadata['duration']:.1f}s")
            if 'audio_codec' in metadata:
                print(f"  Audio: {metadata['audio_codec']} ({metadata['audio_channels']} channels)")
        else:
            print("  ✗ Failed to probe stream")
            results[stream_id] = None

    # Compare results
    print("\n" + "=" * 80)
    print("Comparison Results")
    print("=" * 80)

    if not results:
        print("No streams could be analyzed")
        return results

    # Remove failed probes
    valid_results = {k: v for k, v in results.items() if v is not None}

    if len(valid_results) < 2:
        print("Not enough valid streams to compare")
        return results

    # Check if all streams are identical
    first_stream = list(valid_results.values())[0]
    all_identical = True

    for stream_id, metadata in valid_results.items():
        if metadata['resolution'] != first_stream['resolution']:
            all_identical = False
            break
        if abs(metadata['bitrate'] - first_stream['bitrate']) > 100000:  # 100kbps tolerance
            all_identical = False
            break

    if all_identical:
        print("⚠️  WARNING: All streams appear IDENTICAL!")
        print(f"   Resolution: {first_stream['resolution']}")
        print(f"   Bitrate: ~{first_stream['bitrate'] / 1000:.0f} kbps")
        print(f"   Codec: {first_stream['codec']}")
        print("\n   These are likely DUPLICATES, not different quality versions.")
    else:
        print("✓ Streams have DIFFERENT characteristics:")
        print("\nStream ID    Resolution    Bitrate       Codec    FPS")
        print("-" * 70)
        for stream_id, metadata in valid_results.items():
            print(f"{stream_id:12} {metadata['resolution']:12} "
                  f"{metadata['bitrate']/1000:8.0f} kbps  {metadata['codec']:8} "
                  f"{metadata['fps']:5.1f}")

    return results


def analyze_dispatcharr_episode(episode_uuid):
    """
    Analyze all streams for a specific Dispatcharr episode.

    This queries the Dispatcharr API to get all provider streams,
    then uses ffprobe to compare them.
    """
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
    django.setup()

    from apps.vod.models import Episode, M3UEpisodeRelation

    try:
        episode = Episode.objects.get(uuid=episode_uuid)
        relations = M3UEpisodeRelation.objects.filter(
            episode=episode,
            m3u_account__is_active=True
        ).select_related('m3u_account')

        if not relations:
            print(f"No relations found for episode {episode.name}")
            return

        print(f"Episode: {episode.name}")
        print(f"Series: {episode.series.name}")
        print(f"Found {len(relations)} stream(s) from provider(s)")

        stream_urls = []
        stream_ids = []

        for rel in relations:
            stream_url = rel.get_stream_url()
            if stream_url:
                stream_urls.append(stream_url)
                stream_ids.append(f"{rel.stream_id} ({rel.m3u_account.name})")
            else:
                print(f"Warning: Could not get stream URL for relation {rel.id}")

        if stream_urls:
            compare_streams(stream_urls, stream_ids)
        else:
            print("No valid stream URLs found")

    except Episode.DoesNotExist:
        print(f"Episode with UUID {episode_uuid} not found")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import sys

    print("Stream Difference Verification Tool")
    print("=" * 80)

    # Example usage with manual URLs
    if len(sys.argv) > 1:
        if sys.argv[1] == '--episode':
            # Analyze a Dispatcharr episode
            if len(sys.argv) < 3:
                print("Usage: python verify_stream_differences.py --episode <episode_uuid>")
                sys.exit(1)
            analyze_dispatcharr_episode(sys.argv[2])
        else:
            # Manual URL comparison
            print("Manual URL comparison mode")
            print("Paste stream URLs (one per line), then press Ctrl+D:")
            stream_urls = []
            for line in sys.stdin:
                url = line.strip()
                if url:
                    stream_urls.append(url)

            if len(stream_urls) < 2:
                print("Need at least 2 URLs to compare")
                sys.exit(1)

            stream_ids = [f"Stream {i+1}" for i in range(len(stream_urls))]
            compare_streams(stream_urls, stream_ids)
    else:
        print("\nUsage:")
        print("  1. Analyze Dispatcharr episode:")
        print("     python verify_stream_differences.py --episode <episode_uuid>")
        print("\n  2. Manual URL comparison:")
        print("     python verify_stream_differences.py < urls.txt")
        print("\nExample urls.txt:")
        print("  http://server.com/movie/user/pass/78025.mp4")
        print("  http://server.com/movie/user/pass/78026.mp4")
