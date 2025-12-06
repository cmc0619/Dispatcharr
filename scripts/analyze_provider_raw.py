
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
                    print(f"\n[FOUND!] Series '{name}' S{s}E{e} has {len(streams)} streams:")
                    for st in streams:
                        print(f"   - Stream ID: {st['id']}, Ext: {st['container']}")
                    duplicates_found += 1
        
        if duplicates_found == 0:
            print("\nAnalysis Complete: No duplicates found in the first 10 series sampled.")
            print("To be thorough, we'd need to scan all, but this suggests they are rare.")
        else:
            print(f"\nAnalysis Complete: Found {duplicates_found} cases of multiple streams.")

if __name__ == '__main__':
    analyze_raw_feed()
