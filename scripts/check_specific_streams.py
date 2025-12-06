
import os
import sys
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
django.setup()

from apps.vod.models import M3UEpisodeRelation

def check_streams():
    target_ids = ['707878', '707875']
    print(f"Checking for stream IDs: {target_ids}...")
    
    relations = M3UEpisodeRelation.objects.filter(stream_id__in=target_ids)
    
    if not relations:
        print("❌ Neither stream found in the database. A refresh has not imported them yet, or they were skipped.")
        return

    for rel in relations:
        print(f"\n✅ Found Stream ID: {rel.stream_id}")
        print(f"   Episode ID: {rel.episode.id}")
        print(f"   Episode: {rel.episode}")
        print(f"   Series: {rel.episode.series.name}")
        print(f"   Created: {rel.created_at}")
        print(f"   Updated: {rel.updated_at}")
        
    if len(relations) < len(target_ids):
        found_ids = [r.stream_id for r in relations]
        missing = set(target_ids) - set(found_ids)
        print(f"\n❌ Missing Stream IDs: {missing}")

if __name__ == '__main__':
    check_streams()
