## Summary

Comprehensive fixes for VOD provider data handling issues, resolving duplicate key constraint violations, NULL value crashes, and malformed data imports.

## Issues Resolved

- Fixes #556 - Duplicate key constraint on episodes during VOD refresh
- Fixes #569 - MultipleObjectsReturned errors during episode playback
- Fixes database crashes from NULL/empty names
- Fixes 337 series importing without episodes (malformed provider data)

## Major Changes

### 1. Episode Deduplication Fix
**Problem:** Providers send multiple `stream_ids` for the same episode, causing duplicate key violations.

**Solution:** Added batch-level tracking with `batch_episodes` dictionary to ensure one Episode object with multiple M3UEpisodeRelation objects.

```python
batch_episodes = {}  # Track episodes in current batch
episode_key = (series.id, season_number, episode_number)

if episode_key in batch_episodes:
    episode = batch_episodes[episode_key]  # Reuse
else:
    episode = Episode(...)  # Create once
    batch_episodes[episode_key] = episode
```

**Impact:** Prevents constraint violations when processing duplicate streams.

### 2. NULL/Empty Name Handling
**Problem:** Database crashes when providers send NULL or empty string names.

**Solution:** Changed from `.get("name", "Unknown")` to `.get("name") or "MovieNameNull"`

The `or` operator handles both missing keys AND falsy values (None, ""), while `.get()` default only handles missing keys.

**Files Modified:**
- Movies: `MovieNameNull`
- Series: `SeriesNameNull`  
- Episodes: `EpisodeNameNull`

**Impact:** Prevents NOT NULL constraint violations, allows partial data import.

### 3. Malformed Episode Data Handling
**Problem:** Some providers return episodes as a list instead of dict, causing 337 series to import without episodes.

**Solution:** Added `isinstance()` checks to handle both formats:
- Expected: `{"1": [episodes], "2": [episodes]}`
- Malformed: `[episodes]` (extract season from episode data)

**Impact:** Fixed 337 series that previously had 0 episodes.

### 4. Bulk Update Unsaved Relations Fix
**Problem:** Django error "bulk_update() prohibited due to unsaved related object 'movie'"

**Root Cause:** Code updated `relations_to_create` to use database Movie objects but forgot to do the same for `relations_to_update`.

**Solution:** Added ID mapping for both create and update relations:
```python
# Fix relations_to_update (was missing)
for relation in relations_to_update:
    if id(relation.movie) in created_movies:
        relation.movie = created_movies[id(relation.movie)]
```

**Impact:** Prevents crashes when new movies/series are created and existing relations need to reference them.

### 5. Memory Cleanup
Added explicit cleanup after batch operations to prevent memory buildup in containerized environments:
```python
batch_episodes.clear()
episodes_to_update_set.clear()
del episodes_to_create, episodes_to_update, relations_to_create, relations_to_update
```

### 6. Stream Comparison Tool
Created auto-discovery tool to verify if duplicate streams are identical or quality variants:

```bash
python compare_streams.py
```

Features:
- Automatically finds episodes with multiple streams per provider
- Uses ffprobe to analyze resolution, bitrate, codec, file size
- Reports whether streams are IDENTICAL duplicates or DIFFERENT quality variants
- Helps verify the deduplication fix is working correctly

## Files Modified

- `apps/vod/tasks.py` - Core deduplication, NULL handling, bulk_update fixes
- `compare_streams.py` - Stream comparison and verification tool
- `EPISODE_DEDUP_FIX.md` - User-facing documentation
- `FIXES_DETAILED.md` - Comprehensive technical documentation (573 lines)

## Testing

### Episode Deduplication
1. Run VOD refresh with provider that sends duplicate episode streams
2. Check logs for "Reusing episode from batch" messages
3. Verify database: `SELECT episode_id, COUNT(*) FROM vod_m3uepisoderelation GROUP BY episode_id HAVING COUNT(*) > 1;`

### NULL Name Handling
1. Trigger VOD refresh with provider sending incomplete metadata
2. Verify items import with `*NameNull` placeholders
3. Check: `SELECT name FROM vod_movie WHERE name LIKE '%NameNull';`

### Malformed Data
1. Run VOD refresh with provider sending list-format episodes
2. Verify series that previously had 0 episodes now have episodes
3. Check warning logs about "episodes as list instead of dict"

### Stream Comparison
```bash
python compare_streams.py
```
Analyzes first 10 episodes with duplicate streams from each provider.

## Documentation

All fixes include detailed technical documentation in `FIXES_DETAILED.md` covering:
- Problem descriptions with actual error messages
- Root cause analysis
- Step-by-step scenarios
- Complete fix explanations with code examples
- Testing procedures
- Impact analysis

## Backward Compatibility

✅ No database migrations required  
✅ No API changes  
✅ No configuration changes  
✅ Works with existing data  

All changes are internal to batch processing logic.

## Commits

- Episode deduplication for providers with multiple quality streams
- Malformed episode data handling (list vs dict)
- NULL/empty name handling from VOD providers
- bulk_update error with unsaved movie/series relations
- Memory cleanup after episode batch processing
- Auto-discover duplicate streams comparison tool
- Comprehensive technical documentation

---

**Ready for review and testing**
