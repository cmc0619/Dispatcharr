
import os
import sys
import django
from collections import defaultdict

# Setup Django environment
# Look for settings module in parent directory or current directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
django.setup()

from apps.vod.models import Episode, M3UEpisodeRelation
from apps.m3u.models import M3UAccount

def inspect_duplicates():
    print("Scanning for episodes with multiple streams...")
    
    # helper for finding duplicates
    # We want episodes that have >1 relation for the SAME account
    
    accounts = M3UAccount.objects.filter(is_active=True)
    
    for account in accounts:
        print(f"\nChecking Account: {account.name} (ID: {account.id})")
        
        # Find episodes with count > 1
        # We can't easily use .annotate() on the relation table filtering by duplicate episode_id easily in one go 
        # without grouping. 
        
        from django.db.models import Count
        dupes = M3UEpisodeRelation.objects.filter(m3u_account=account).values('episode').annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        print(f"Found {dupes.count()} episodes with multiple streams.")
        
        if dupes.count() == 0:
            continue
            
        # Inspect the first 5 examples
        example_ids = [d['episode'] for d in dupes[:5]]
        
        for ep_id in example_ids:
            try:
                episode = Episode.objects.get(id=ep_id)
                relations = M3UEpisodeRelation.objects.filter(episode=episode, m3u_account=account)
                
                print(f"\nWARNING: Episode '{episode.name}' (S{episode.season_number}E{episode.episode_number}) has {relations.count()} streams:")
                
                for i, rel in enumerate(relations, 1):
                    # check custom properties for any hints
                    info = rel.custom_properties.get('info', {}) if rel.custom_properties else {}
                    title_in_info = info.get('title', 'N/A')
                    container = rel.container_extension
                    
                    print(f"  Stream #{i}:")
                    print(f"    - Stream ID: {rel.stream_id}")
                    print(f"    - Container: {container}")
                    print(f"    - Title in metadata: {title_in_info}") 
                    # Add any other differentiating fields here if found
                    
                    # Sometimes differences are in 'name' or 'type' inside info
                    
            except Episode.DoesNotExist:
                pass

if __name__ == '__main__':
    inspect_duplicates()
