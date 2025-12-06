
import os
import sys
import django
import json
from collections import defaultdict

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
django.setup()

from apps.m3u.models import M3UAccount
from core.xtream_codes import Client as XtreamCodesClient
import subprocess

def check_stream_health(url):
    """
    Returns (is_valid, summary_string)
    """
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            '-analyzeduration', '5000000',
            '-probesize', '10000000',
            '-user_agent', 'VLC/3.0.18-Vetinari',
            url
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return False, f"ffprobe ERROR: {result.stderr[:50]}"
            
        try:
            data = json.loads(result.stdout)
        except:
            return False, "Invalid JSON output"
            
        if not data:
            return False, "Empty Response"
            
        streams = data.get('streams', [])
        if not streams:
            return False, "NO STREAMS FOUND (Ghost File)"
            
        video = next((s for s in streams if s.get('codec_type') == 'video'), None)
        audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
        
        details = []
        if video:
            details.append(f"Video: {video.get('codec_name', 'unknown')} ({video.get('width')}x{video.get('height')})")
        else:
            details.append("Video: None")
            
        if audio:
            details.append(f"Audio: {audio.get('codec_name', 'unknown')}")
            
        return True, ", ".join(details)
        
    except Exception as e:
        return False, f"Exception: {str(e)}"

def analyze_raw_feed():
    print("Connecting to provider to analyze RAW data...")
    
    account = M3UAccount.objects.filter(is_active=True, account_type='XC').first()
    if not account:
        print("No active XC account found.")
        return

    print(f"Using account: {account.name}")
    
    with XtreamCodesClient(
        account.server_url,
        account.username,
        account.password,
        account.get_user_agent().user_agent
    ) as client:
        
        # 1. Fetch all series to get IDs
        print("Fetching series list...")
        all_series = client.get_series()
        print(f"Found {len(all_series)} series.")
        
        # 2. Pick top 5 series to analyze in depth (or scan all if user wants, but that's slow)
        # We'll scan a few to demonstrate
        
        duplicates_found = 0
        
        for i, series_info in enumerate(all_series[:10]):
            series_id = series_info.get('series_id')
            name = series_info.get('name')
            
            # print(f"Checking series: {name}...")
            
            detailed_info = client.get_series_info(series_id)
            episodes = detailed_info.get('episodes', {})
            
            # Episodes might be list or dict
            all_eps = []
            if isinstance(episodes, dict):
                for season, eps in episodes.items():
                    all_eps.extend(eps)
            elif isinstance(episodes, list):
                all_eps = episodes
            
            # Logic to find duplicates in raw feed
            # Key = (Season, Episode)
            # Value = List of Stream IDs
            ep_map = defaultdict(list)
            
            for ep in all_eps:
                s = ep.get('season') or ep.get('season_number')
                e = ep.get('episode_num')
                stream_id = ep.get('id')
                container = ep.get('container_extension')
                
                key = (s, e)
                ep_map[key].append({'id': stream_id, 'container': container})
                
            # Check for dupes
            for (s, e), streams in ep_map.items():
                if len(streams) > 1:
                    print(f"\n{'='*80}")
                    print(f"[FOUND!] Series '{name}' S{s}E{e} has {len(streams)} streams:")
                    
                    for stream_entry in streams:
                        stream_id = stream_entry['id']
                        container = stream_entry['container']
                        
                        # Generate URLs (assuming XC format)
                        stream_url = client.get_episode_stream_url(stream_id, container)
                        
                        print(f"\n  --- STREAM ID: {stream_id} ---")
                        print(f"  URL: {stream_url}")
                        
                        # Validate the stream
                        is_valid, summary = check_stream_health(stream_url)
                        if is_valid:
                             print(f"  STATUS: VALID ({summary})")
                        else:
                             print(f"  STATUS: BROKEN/NULL ({summary})")

                        # Find the full original JSON object for this stream
                        original_data = next((ep for ep in all_eps if ep.get('id') == stream_id), None)
                        
                        if original_data:
                            print("  FULL MSG:")
                            print(json.dumps(original_data, indent=4))
                        else:
                            print("  (Original JSON not found??)")
                    
                    duplicates_found += 1
        
        if duplicates_found == 0:
            print("\nAnalysis Complete: No duplicates found in the first 10 series sampled.")
            print("To be thorough, we'd need to scan all, but this suggests they are rare.")
        else:
            print(f"\nAnalysis Complete: Found {duplicates_found} cases of multiple streams.")

if __name__ == '__main__':
    analyze_raw_feed()
