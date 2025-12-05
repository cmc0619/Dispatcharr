# Episode Deduplication Fix for Issues #556 and #569

## Problem Statement

When a VOD provider (e.g., Chico) returns multiple stream_ids for the same episode (representing different quality versions), Dispatcharr was creating duplicate Episode objects, causing:

**Issue #556**: Duplicate key constraint violation
```
ERROR: duplicate key value violates unique constraint "vod_episode_series_id_season_number__73053ba7_uniq"
DETAIL: Key (series_id, season_number, episode_number)=(11, 9, 2) already exists.
```

**Issue #569**: Multiple M3UEpisodeRelation objects causing playback errors
```
M3UEpisodeRelation.MultipleObjectsReturned: get() returned more than one M3UEpisodeRelation -- it returned 2!
```

## Root Cause

### Example Scenario
Provider returns 5 streams for MasterChef Junior S09E02:
- Stream 78025: S09E02 (1080p)
- Stream 78026: S09E02 (720p)
- Stream 78027: S09E02 (480p)
- Stream 78028: S09E02 (360p)
- Stream 78029: S09E02 (SD)

### Old Code Behavior
```python
for episode_data in all_episodes_data:  # 5 iterations
    episode_key = (series.id, 9, 2)
    episode = existing_episodes.get(episode_key)  # Only checks DB, not batch

    if not episode:
        episode = Episode(...)  # Creates 5 Episode objects!
        episodes_to_create.append(episode)  # All 5 added!
```

**Result**: Tries to insert 5 Episodes with the same `(series_id=11, season_number=9, episode_number=2)`

## The Fix

### Changes Made to `apps/vod/tasks.py`

**1. Added Batch Tracking** (Lines 1198-1204)
```python
episodes_to_update_set = set()  # Track episodes already queued for update
batch_episodes = {}  # Track episodes in THIS batch
```

**2. Modified Episode Lookup** (Lines 1235-1299)
```python
# Check batch FIRST, then database
if episode_key in batch_episodes:
    episode = batch_episodes[episode_key]  # Reuse!
    logger.debug(f"Reusing episode from batch: {episode_name}")
else:
    episode = existing_episodes.get(episode_key)  # Check DB

    if episode:
        # Update (but only once)
        if updated and id(episode) not in episodes_to_update_set:
            episodes_to_update.append(episode)
            episodes_to_update_set.add(id(episode))
        batch_episodes[episode_key] = episode
    else:
        # Create (only once)
        episode = Episode(...)
        episodes_to_create.append(episode)
        batch_episodes[episode_key] = episode
```

**3. Enhanced Logging** (Lines 1390-1396)
```python
logger.info(f"Batch processed {total_streams} stream(s) -> {unique_episodes} unique episode(s)")
logger.info(f"Episodes: {len(episodes_to_create)} new, {len(episodes_to_update)} updated")
logger.info(f"Relations: {relations_created_count} new, {len(relations_to_update)} updated")
```

### New Behavior

**First Run (Empty DB):**
```
Iteration 1 (stream 78025): Creates Episode, adds to batch_episodes
Iteration 2 (stream 78026): Finds Episode in batch_episodes, reuses it
Iteration 3 (stream 78027): Finds Episode in batch_episodes, reuses it
Iteration 4 (stream 78028): Finds Episode in batch_episodes, reuses it
Iteration 5 (stream 78029): Finds Episode in batch_episodes, reuses it

Result: 1 Episode object, 5 M3UEpisodeRelation objects (correct!)
```

**Subsequent Runs (Episode exists in DB):**
```
Iteration 1: Finds Episode in DB, queues for update, adds to batch_episodes
Iteration 2-5: Finds Episode in batch_episodes, reuses it (no duplicate updates)

Result: 1 Episode updated once, 5 M3UEpisodeRelation objects updated
```

## Verification

### Expected Log Output (After Fix)
```
INFO apps.vod.tasks Batch processing 5 stream entries for series MasterChef Junior (2013)
DEBUG apps.vod.tasks Reusing episode from batch: MasterChef Junior - S09E02 - Episode 2 (S09E02)
DEBUG apps.vod.tasks Reusing episode from batch: MasterChef Junior - S09E02 - Episode 2 (S09E02)
DEBUG apps.vod.tasks Reusing episode from batch: MasterChef Junior - S09E02 - Episode 2 (S09E02)
DEBUG apps.vod.tasks Reusing episode from batch: MasterChef Junior - S09E02 - Episode 2 (S09E02)
INFO apps.vod.tasks Batch processed 5 stream(s) -> 1 unique episode(s) for series MasterChef Junior (2013)
INFO apps.vod.tasks Episodes: 1 new, 0 updated
INFO apps.vod.tasks Relations: 5 new, 0 updated
```

### Database State After Processing
```sql
-- One Episode record
SELECT * FROM vod_episode WHERE series_id = 11 AND season_number = 9 AND episode_number = 2;
-- Returns: 1 row

-- Five M3UEpisodeRelation records (different stream_ids, same episode)
SELECT stream_id, episode_id FROM vod_m3uepisoderelation WHERE stream_id IN ('78025', '78026', '78027', '78028', '78029');
-- Returns: 5 rows, all with the same episode_id
```

### UI Behavior
- **Series page**: Shows ONE episode (S09E02)
- **Provider dropdown**: Shows 5 streams
  - Chico - 1080p (Stream 78025)
  - Chico - 720p (Stream 78026)
  - Chico - 480p (Stream 78027)
  - Chico - 360p (Stream 78028)
  - Chico - SD (Stream 78029)
- **Playback**: Works correctly, no `MultipleObjectsReturned` error

## Impact

### Issues Resolved
- ✅ **#556**: No more duplicate key constraint violations
- ✅ **#569**: No more `MultipleObjectsReturned` errors during playback

### Performance Improvements
- Eliminates redundant Episode creation attempts
- Reduces database constraint violations
- Prevents duplicate update operations on the same Episode

### Edge Cases Handled
1. **Multiple providers with same episode**: Each provider creates its own relations
2. **Concurrent refreshes**: `ignore_conflicts=True` on bulk_create handles race conditions
3. **Mixed new/existing episodes**: Correctly deduplicates within batch for both cases

## Testing

### Manual Test Steps
1. Configure M3U account with VOD content that has multiple quality versions
2. Trigger VOD refresh
3. Check logs for "Reusing episode from batch" messages
4. Verify log shows "X stream(s) -> Y unique episode(s)" where Y < X
5. Check database: One Episode record, multiple M3UEpisodeRelation records
6. Test playback: Should work without MultipleObjectsReturned errors

### Automated Test
Run the included test script:
```bash
python test_episode_dedup.py
```

Expected output:
```
✓ PASS: Created exactly 1 Episode object (correct)
✓ PASS: Created exactly 5 M3UEpisodeRelation objects (correct)
✓ PASS: All 5 relations point to the same Episode
✓ ALL TESTS PASSED!
```

## Backward Compatibility

This fix is **fully backward compatible**:
- No database migrations required
- No API changes
- No configuration changes
- Works with existing data

The fix only changes the internal batch processing logic to avoid creating duplicates.

## Future Improvements

Consider these enhancements in future PRs:
1. Add episode deduplication metric to admin dashboard
2. Add database constraint check before bulk operations
3. Add warning when same episode appears multiple times in provider response
4. Create cleanup task to merge duplicate episodes from before the fix

## Credits

Fix developed for issues:
- https://github.com/Dispatcharr/Dispatcharr/issues/556
- https://github.com/Dispatcharr/Dispatcharr/issues/569

Related to PR #674 (closed before merge).
