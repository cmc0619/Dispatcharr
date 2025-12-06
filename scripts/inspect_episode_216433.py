
import os
import sys
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
django.setup()

from apps.vod.models import Episode, M3UEpisodeRelation

def inspect_episode():
    # ID from the user's log
    target_ep_id = 216433
    
    print(f"Inspecting Episode ID: {target_ep_id} ...")
    
    try:
        ep = Episode.objects.get(id=target_ep_id)
        print(f"✅ Found Episode: {ep}")
        print(f"   Series: {ep.series.name}")
        print(f"   Season: {ep.season_number}")
        print(f"   Episode: {ep.episode_number}")
        print(f"   UUID: {ep.uuid}")
        
        print("\nChecking for attached streams (M3UEpisodeRelation)...")
        relations = M3UEpisodeRelation.objects.filter(episode=ep)
        
        if not relations:
            print("❌ No streams attached to this episode!")
        else:
            print(f"Found {len(relations)} stream(s):")
            for i, rel in enumerate(relations):
                print(f"  {i+1}. Stream ID: '{rel.stream_id}' (Length: {len(rel.stream_id)})")
                print(f"     Provider: {rel.m3u_account.name}")
                print(f"     Container: {rel.container_extension}")
                print(f"     Created: {rel.created_at}")
                
    except Episode.DoesNotExist:
        print(f"❌ Episode {target_ep_id} NOT FOUND in database.")

if __name__ == '__main__':
    inspect_episode()
