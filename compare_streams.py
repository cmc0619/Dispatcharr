#!/usr/bin/env python3
"""
Simple stream comparison tool that works without Django.
Uses ffprobe to compare stream quality.
"""

import subprocess
import json
import sys

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
            'fps': eval(video_stream.get('r_frame_rate', '0/1')) if video_stream.get('r_frame_rate') else 0,
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


def get_episode_streams_from_api(episode_uuid, base_url="http://localhost:5656"):
    """Get stream URLs for an episode from Dispatcharr API."""
    import requests

    try:
        # Get episode details
        response = requests.get(f"{base_url}/api/vod/episodes/{episode_uuid}/")
        if response.status_code != 200:
            print(f"Failed to get episode: {response.status_code}")
            return None

        episode_data = response.json()

        # Get provider relations
        providers = episode_data.get('providers', [])
        if not providers:
            print("No providers found for this episode")
            return None

        print(f"Episode: {episode_data.get('name', 'Unknown')}")
        print(f"Series: {episode_data.get('series', {}).get('name', 'Unknown')}")
        print(f"Found {len(providers)} stream(s)\n")

        # Build stream URLs
        streams = []
        for provider in providers:
            stream_id = provider.get('stream_id')
            account = provider.get('m3u_account', {})

            # Build the stream URL from relation
            stream_url = None
            if 'episode' in provider:
                # Use the get_stream_url method via the relation
                container = provider.get('container_extension', 'mp4')
                # This is the Xtream Codes URL format
                if account.get('account_type') == 'XC':
                    server_url = account.get('server_url', '').rstrip('/')
                    username = account.get('username', '')
                    password = account.get('password', '')
                    stream_url = f"{server_url}/series/{username}/{password}/{stream_id}.{container}"

            if stream_url:
                streams.append({
                    'id': stream_id,
                    'url': stream_url,
                    'account': account.get('name', 'Unknown')
                })

        return streams

    except Exception as e:
        print(f"API error: {e}")
        return None


if __name__ == "__main__":
    print("=" * 80)
    print("Stream Comparison Tool (Standalone)")
    print("=" * 80)

    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  Compare streams for a Dispatcharr episode:")
        print("    python compare_streams.py --episode <episode_uuid>")
        print("\n  Compare specific URLs:")
        print("    python compare_streams.py <url1> <url2> <url3> ...")
        print("\nExample:")
        print("  python compare_streams.py --episode f30a37c0-cc16-4879-8dbc-2a21505877d7")
        sys.exit(1)

    results = {}

    if sys.argv[1] == '--episode':
        # Get streams from Dispatcharr API
        if len(sys.argv) < 3:
            print("Error: Missing episode UUID")
            sys.exit(1)

        episode_uuid = sys.argv[2]
        base_url = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:5656"

        streams = get_episode_streams_from_api(episode_uuid, base_url)
        if not streams:
            sys.exit(1)

        for stream in streams:
            print(f"Analyzing stream {stream['id']} ({stream['account']})...")
            print(f"  URL: {stream['url'][:80]}...")

            metadata = ffprobe_stream(stream['url'], timeout=15)
            if metadata:
                results[stream['id']] = metadata
                print(f"  ✓ Resolution: {metadata['resolution']}")
                print(f"  ✓ Codec: {metadata['codec']}")
                print(f"  ✓ Bitrate: {metadata['bitrate'] / 1000:.0f} kbps")
                print(f"  ✓ File size: {metadata['file_size'] / (1024*1024):.1f} MB")
                if metadata['fps'] > 0:
                    print(f"  ✓ FPS: {metadata['fps']:.2f}")
                if 'audio_codec' in metadata:
                    print(f"  ✓ Audio: {metadata['audio_codec']}")
            else:
                results[stream['id']] = None
            print()
    else:
        # Direct URL comparison
        stream_urls = sys.argv[1:]
        print(f"Comparing {len(stream_urls)} stream(s)...\n")

        for i, url in enumerate(stream_urls):
            stream_id = f"Stream_{i+1}"
            print(f"Analyzing {stream_id}...")
            print(f"  URL: {url[:80]}...")

            metadata = ffprobe_stream(url, timeout=15)
            if metadata:
                results[stream_id] = metadata
                print(f"  ✓ Resolution: {metadata['resolution']}")
                print(f"  ✓ Bitrate: {metadata['bitrate'] / 1000:.0f} kbps")
            else:
                results[stream_id] = None
            print()

    # Compare results
    print("=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)

    valid_results = {k: v for k, v in results.items() if v is not None}

    if len(valid_results) < 2:
        print("Not enough valid streams to compare")
        sys.exit(0)

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
        print("   The provider may be sending the same stream with multiple IDs.")
    else:
        print("\n✓ Streams have DIFFERENT characteristics:\n")
        print(f"{'Stream ID':<20} {'Resolution':<15} {'Bitrate':<12} {'Size':<10} {'Codec'}")
        print("-" * 80)
        for stream_id, metadata in valid_results.items():
            print(f"{stream_id:<20} {metadata['resolution']:<15} "
                  f"{metadata['bitrate']/1000:>8.0f} kbps "
                  f"{metadata['file_size']/(1024*1024):>6.1f} MB  {metadata['codec']}")

        print("\n   These appear to be legitimate quality variants.")
