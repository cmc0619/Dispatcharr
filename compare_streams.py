#!/usr/bin/env python3
"""
Stream comparison tool that automatically discovers episodes with duplicate streams.
Analyzes the first 10 episodes with multiple streams from each provider using ffprobe.
"""

import os
import sys
import django
import subprocess
import json
from collections import defaultdict
from fractions import Fraction

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
django.setup()

from django.db.models import Count
from apps.vod.models import Episode, M3UEpisodeRelation
from apps.m3u.models import M3UAccount


def ffprobe_stream(url, timeout=10):
    """Use ffprobe to get stream metadata."""
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            '-analyzeduration', '5000000',
            '-probesize', '10000000',
            url
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode != 0:
            print(f"  ✗ ffprobe failed: {result.stderr[:100]}")
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
            print("  ✗ No video stream found")
            return None

        metadata = {
            'resolution': f"{video_stream.get('width', 0)}x{video_stream.get('height', 0)}",
            'width': video_stream.get('width', 0),
            'height': video_stream.get('height', 0),
            'codec': video_stream.get('codec_name', 'unknown'),
            'bitrate': int(data.get('format', {}).get('bit_rate', 0)),
            'duration': float(data.get('format', {}).get('duration', 0)),
            'fps': float(Fraction(video_stream.get('r_frame_rate', '0/1'))) if video_stream.get('r_frame_rate') else 0,
            'file_size': int(data.get('format', {}).get('size', 0)),
        }

        if audio_stream:
            metadata['audio_codec'] = audio_stream.get('codec_name', 'unknown')
            metadata['audio_channels'] = audio_stream.get('channels', 0)

        return metadata

    except subprocess.TimeoutExpired:
        print(f"  ✗ ffprobe timeout after {timeout}s")
        return None
    except Exception as e:
        print(f"  ✗ ffprobe error: {e}")
        return None


def find_episodes_with_duplicate_streams():
    """
    Find episodes that have multiple M3UEpisodeRelation entries.
    Returns dict: {account: [episode_ids with multiple streams]}
    """
    print("=== Scanning database for episodes with duplicate streams ===\n")

    # Get all active M3U accounts
    accounts = M3UAccount.objects.filter(is_active=True)

    if not accounts.exists():
        print("ERROR: No active M3U accounts found")
        return {}

    episodes_by_account = {}

    for account in accounts:
        print(f"Checking provider: {account.name}")

        # Find episodes with multiple streams from this account
        # Group by episode and count relations
        duplicate_episodes = (
            M3UEpisodeRelation.objects
            .filter(m3u_account=account)
            .values('episode')
            .annotate(stream_count=Count('id'))
            .filter(stream_count__gt=1)
            .order_by('-stream_count')
        )

        if duplicate_episodes:
            episode_ids = [item['episode'] for item in duplicate_episodes[:10]]
            episodes_by_account[account] = episode_ids
            print(f"  Found {len(duplicate_episodes)} episodes with multiple streams")
            print(f"  Will analyze first {min(10, len(duplicate_episodes))} episodes\n")
        else:
            print(f"  No episodes with multiple streams found\n")

    return episodes_by_account


def analyze_episode_streams(account, episode):
    """Analyze all streams for a given episode from a specific account."""
    relations = M3UEpisodeRelation.objects.filter(
        m3u_account=account,
        episode=episode
    )

    print("=" * 80)
    print(f"Episode: {episode.name}")
    print(f"Series: {episode.series.name}")
    print(f"Season {episode.season_number}, Episode {episode.episode_number}")
    print(f"Provider: {account.name}")
    print(f"Found {relations.count()} stream(s)")
    print("=" * 80)

    results = {}

    for rel in relations:
        stream_url = rel.get_stream_url()
        if not stream_url:
            print(f"\nStream {rel.stream_id}:")
            print(f"  ✗ Could not generate stream URL")
            continue

        print(f"\nAnalyzing stream {rel.stream_id}...")
        print(f"  URL: {stream_url[:80]}...")

        metadata = ffprobe_stream(stream_url, timeout=15)
        if metadata:
            results[rel.stream_id] = metadata
            print(f"  ✓ Resolution: {metadata['resolution']}")
            print(f"  ✓ Codec: {metadata['codec']}")
            print(f"  ✓ Bitrate: {metadata['bitrate'] / 1000:.0f} kbps")
            print(f"  ✓ File size: {metadata['file_size'] / (1024*1024):.1f} MB")
            if metadata['fps'] > 0:
                print(f"  ✓ FPS: {metadata['fps']:.2f}")
            if 'audio_codec' in metadata:
                print(f"  ✓ Audio: {metadata['audio_codec']} ({metadata.get('audio_channels', 0)} channels)")
        else:
            results[rel.stream_id] = None

    # Compare results
    print("\n" + "=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)

    valid_results = {k: v for k, v in results.items() if v is not None}

    if len(valid_results) < 2:
        print("Not enough valid streams to compare\n")
        return False

    # Check if all identical
    first = list(valid_results.values())[0]
    all_identical = True

    for metadata in valid_results.values():
        if metadata['resolution'] != first['resolution']:
            all_identical = False
            break
        # Allow 5% bitrate variance
        if abs(metadata['bitrate'] - first['bitrate']) > first['bitrate'] * 0.05:
            all_identical = False
            break
        if abs(metadata['file_size'] - first['file_size']) > first['file_size'] * 0.05:
            all_identical = False
            break

    if all_identical:
        print("\n⚠️  WARNING: All streams appear IDENTICAL!\n")
        print(f"   Resolution: {first['resolution']}")
        print(f"   Bitrate:    {first['bitrate'] / 1000:.0f} kbps")
        print(f"   Codec:      {first['codec']}")
        print(f"   File size:  {first['file_size'] / (1024*1024):.1f} MB")
        print("\n   These are likely DUPLICATES, not different quality versions.")
        print("   The provider may be sending the same stream with multiple IDs.\n")
        return True  # Identical
    else:
        print("\n✓ Streams have DIFFERENT characteristics:\n")
        print(f"{'Stream ID':<20} {'Resolution':<15} {'Bitrate':<12} {'Size':<10} {'Codec'}")
        print("-" * 80)
        for stream_id, metadata in valid_results.items():
            print(f"{stream_id:<20} {metadata['resolution']:<15} "
                  f"{metadata['bitrate']/1000:>8.0f} kbps "
                  f"{metadata['file_size']/(1024*1024):>6.1f} MB  {metadata['codec']}")
        print("\n   These appear to be legitimate quality variants.\n")
        return False  # Different


def main():
    print("=" * 80)
    print("Automatic Stream Comparison Tool")
    print("=" * 80)
    print()

    # Find episodes with duplicate streams
    episodes_by_account = find_episodes_with_duplicate_streams()

    if not episodes_by_account:
        print("No episodes with duplicate streams found in any provider.")
        return

    # Analyze each provider's duplicate episodes
    total_analyzed = 0
    identical_count = 0
    different_count = 0

    for account, episode_ids in episodes_by_account.items():
        print(f"\n{'=' * 80}")
        print(f"ANALYZING PROVIDER: {account.name}")
        print(f"{'=' * 80}\n")

        for episode_id in episode_ids:
            try:
                episode = Episode.objects.get(id=episode_id)
                is_identical = analyze_episode_streams(account, episode)
                total_analyzed += 1

                if is_identical:
                    identical_count += 1
                else:
                    different_count += 1

                print("\n" + "-" * 80 + "\n")

            except Episode.DoesNotExist:
                print(f"ERROR: Episode with ID {episode_id} not found\n")
                continue
            except Exception as e:
                print(f"ERROR analyzing episode {episode_id}: {e}\n")
                continue

    # Summary
    print("\n" + "=" * 80)
    print("OVERALL SUMMARY")
    print("=" * 80)
    print(f"Total episodes analyzed: {total_analyzed}")
    print(f"Episodes with IDENTICAL streams: {identical_count}")
    print(f"Episodes with DIFFERENT streams: {different_count}")

    if identical_count > 0:
        print("\n⚠️  Warning: Some providers are sending duplicate streams with different IDs.")
        print("   This is the root cause of issue #556 and #569.")
        print("   The deduplication fix in apps/vod/tasks.py handles this correctly.")

    if different_count > 0:
        print("\n✓ Some streams represent legitimate quality variants (different resolution/bitrate).")

    print("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
