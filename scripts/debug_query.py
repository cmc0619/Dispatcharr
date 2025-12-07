
import os
import sys
import django
from django.db.models import Count

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
django.setup()

from apps.vod.models import M3UEpisodeRelation, M3UAccount

def debug_query():
    print("Debugging query logic...")
    
    # 1. Check Accounts
    accounts = M3UAccount.objects.filter(is_active=True)
    print(f"Active Accounts: {[a.name for a in accounts]}")
    
    for account in accounts:
        print(f"\nChecking Provider: {account.name}")
        
        # 2. Raw Count
        total_rels = M3UEpisodeRelation.objects.filter(m3u_account=account).count()
        print(f"  Total Relations: {total_rels}")
        
        # 3. Manual Grouping (Python)
        all_rels = M3UEpisodeRelation.objects.filter(m3u_account=account).values('episode_id', 'stream_id')
        ep_counts = {}
        for r in all_rels:
            ep_id = r['episode_id']
            ep_counts[ep_id] = ep_counts.get(ep_id, 0) + 1
            
        manual_dupes = {k:v for k,v in ep_counts.items() if v > 1}
        print(f"  Manual Python Count > 1: {len(manual_dupes)} episodes")
        
        # 4. ORM Query (The failing one)
        orm_dupes = (
            M3UEpisodeRelation.objects
            .filter(m3u_account=account)
            .values('episode')
            .annotate(stream_count=Count('id'))
            .filter(stream_count__gt=1)
        )
        print(f"  ORM Query Count > 1: {orm_dupes.count()} episodes")
        
        if len(manual_dupes) > 0 and orm_dupes.count() == 0:
            print("  mismatch detected! ORM query is flawed.")
            
            # Additional debug for ORM
            print("  Query SQL:", orm_dupes.query)

if __name__ == '__main__':
    debug_query()
