#!/usr/bin/env python
"""
Test script to verify episode deduplication fix for issues #556 and #569.

This simulates the scenario where a provider returns multiple stream_ids
for the same episode (different quality versions).
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
django.setup()

from apps.vod.models import Series, Episode, M3UEpisodeRelation
from apps.m3u.models import M3UAccount
from apps.vod.tasks import batch_process_episodes
from django.utils import timezone

def test_episode_deduplication():
    """
    Test that multiple streams for the same episode only create ONE Episode object
    but multiple M3UEpisodeRelation objects.
    """
    print("=" * 80)
    print("Testing Episode Deduplication Fix (Issues #556 and #569)")
    print("=" * 80)

    # Get or create test data
    try:
        account = M3UAccount.objects.filter(is_active=True).first()
        if not account:
            print("ERROR: No active M3U account found. Please configure an M3U account first.")
            return False

        series = Series.objects.filter(name__icontains="MasterChef").first()
        if not series:
            print("WARNING: No MasterChef series found. Creating test series...")
            series = Series.objects.create(
                name="Test Series for Episode Dedup",
                description="Test series",
                year=2024
            )

        print(f"\nUsing Account: {account.name}")
        print(f"Using Series: {series.name} (ID: {series.id})")

        # Simulate provider returning 5 different stream_ids for the SAME episode
        # This is what Chico does - returns different quality versions
        episodes_data = {
            "9": [  # Season 9
                {
                    "id": "78025",
                    "title": "MasterChef Junior - S09E02 - Episode 2",
                    "episode_num": 2,
                    "container_extension": "mp4",
                    "info": {
                        "plot": "Episode 2 description",
                        "rating": "7.5",
                        "duration_secs": 9000,
                        "tmdb_id": "3411747",
                        "movie_image": "http://example.com/image1.jpg"
                    }
                },
                {
                    "id": "78026",  # Different stream_id, SAME episode
                    "title": "MasterChef Junior - S09E02 - Episode 2",
                    "episode_num": 2,  # Same episode number
                    "container_extension": "mp4",
                    "info": {
                        "plot": "Episode 2 description",
                        "rating": "7.5",
                        "duration_secs": 9000,
                        "tmdb_id": "3411747",
                        "movie_image": "http://example.com/image2.jpg"  # Different image
                    }
                },
                {
                    "id": "78027",  # Third stream, SAME episode
                    "title": "MasterChef Junior - S09E02 - Episode 2",
                    "episode_num": 2,
                    "container_extension": "mp4",
                    "info": {
                        "plot": "Episode 2 description",
                        "rating": "7.5",
                        "duration_secs": 9000,
                        "tmdb_id": "3411747",
                        "movie_image": "http://example.com/image3.jpg"
                    }
                },
                {
                    "id": "78028",  # Fourth stream
                    "title": "MasterChef Junior - S09E02 - Episode 2",
                    "episode_num": 2,
                    "container_extension": "mp4",
                    "info": {
                        "plot": "Episode 2 description",
                        "rating": "7.5",
                        "duration_secs": 9000,
                        "tmdb_id": "3411747",
                        "movie_image": "http://example.com/image4.jpg"
                    }
                },
                {
                    "id": "78029",  # Fifth stream
                    "title": "MasterChef Junior - S09E02 - Episode 2",
                    "episode_num": 2,
                    "container_extension": "mp4",
                    "info": {
                        "plot": "Episode 2 description",
                        "rating": "7.5",
                        "duration_secs": 9000,
                        "tmdb_id": "3411747",
                        "movie_image": "http://example.com/image5.jpg"
                    }
                }
            ]
        }

        print(f"\nSimulating provider returning 5 stream_ids for S09E02...")
        print("Stream IDs: 78025, 78026, 78027, 78028, 78029")

        # Get initial counts
        initial_episode_count = Episode.objects.filter(series=series, season_number=9, episode_number=2).count()
        initial_relation_count = M3UEpisodeRelation.objects.filter(m3u_account=account).count()

        print(f"\nBefore batch_process_episodes:")
        print(f"  Episodes for S09E02: {initial_episode_count}")
        print(f"  Relations for account: {initial_relation_count}")

        # Run the batch processing
        print(f"\nRunning batch_process_episodes...")
        batch_process_episodes(account, series, episodes_data, scan_start_time=timezone.now())

        # Get final counts
        final_episode_count = Episode.objects.filter(series=series, season_number=9, episode_number=2).count()
        final_relation_count = M3UEpisodeRelation.objects.filter(
            m3u_account=account,
            stream_id__in=["78025", "78026", "78027", "78028", "78029"]
        ).count()

        print(f"\nAfter batch_process_episodes:")
        print(f"  Episodes for S09E02: {final_episode_count}")
        print(f"  Relations created: {final_relation_count}")

        # Verify expectations
        print(f"\n" + "=" * 80)
        print("VERIFICATION:")
        print("=" * 80)

        episodes_created = final_episode_count - initial_episode_count
        relations_created = final_relation_count - initial_relation_count

        success = True

        # Should only create ONE episode
        if episodes_created == 1:
            print("✓ PASS: Created exactly 1 Episode object (correct)")
        else:
            print(f"✗ FAIL: Created {episodes_created} Episode objects (expected 1)")
            success = False

        # Should create 5 relations
        if relations_created == 5:
            print("✓ PASS: Created exactly 5 M3UEpisodeRelation objects (correct)")
        else:
            print(f"✗ FAIL: Created {relations_created} M3UEpisodeRelation objects (expected 5)")
            success = False

        # Verify all relations point to the same episode
        episode = Episode.objects.filter(series=series, season_number=9, episode_number=2).first()
        if episode:
            relations = M3UEpisodeRelation.objects.filter(
                m3u_account=account,
                stream_id__in=["78025", "78026", "78027", "78028", "78029"]
            )
            unique_episodes = set(rel.episode.id for rel in relations)
            if len(unique_episodes) == 1:
                print(f"✓ PASS: All 5 relations point to the same Episode (ID: {episode.id})")
            else:
                print(f"✗ FAIL: Relations point to {len(unique_episodes)} different Episodes (expected 1)")
                success = False
        else:
            print("✗ FAIL: Could not find the Episode object")
            success = False

        print("=" * 80)
        if success:
            print("✓ ALL TESTS PASSED! The deduplication fix is working correctly.")
            print("\nThis fix resolves:")
            print("  - Issue #556: Duplicate key constraint violation")
            print("  - Issue #569: Multiple M3UEpisodeRelation causing playback errors")
        else:
            print("✗ SOME TESTS FAILED! The fix may not be working correctly.")

        return success

    except Exception as e:
        print(f"\n✗ ERROR during test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_episode_deduplication()
