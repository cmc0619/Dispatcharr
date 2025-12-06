
import os
import sys
import django
from django.db.models import Count

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
django.setup()

from apps.vod.models import Episode, Series

def check_duplicate_episodes():
    print("Checking for duplicate Episode objects (same Series, Season, Number)...")
    
    duplicates = (
        Episode.objects.values('series', 'season_number', 'episode_number')
        .annotate(count=Count('id'))
        .filter(count__gt=1)
        .order_by('-count')
    )
    
    if not duplicates:
        print("No duplicate Episode objects found. Database integrity looks good.")
        return

    print(f"Found {len(duplicates)} sets of duplicate episodes!\n")
    
    for item in duplicates[:10]:
        series_id = item['series']
        season = item['season_number']
        ep_num = item['episode_number']
        count = item['count']
        
        try:
            series = Series.objects.get(id=series_id)
            series_name = series.name
        except Series.DoesNotExist:
            series_name = f"Unknown Series ({series_id})"
            
        print(f"Series: {series_name} | S{season} E{ep_num} | Count: {count}")
        
    print(f"\nTotal duplicate sets: {len(duplicates)}")
    print("This explains why compare_streams.py found nothing - streams are split across these duplicates.")

if __name__ == '__main__':
    check_duplicate_episodes()
