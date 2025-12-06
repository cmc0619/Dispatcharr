# Detailed Fix Documentation

This document provides comprehensive technical explanations for all fixes applied in this branch to resolve issues #556 and #569, along with related improvements.

## Table of Contents

1. [Episode Deduplication Fix](#1-episode-deduplication-fix)
2. [Malformed Episode Data Handling](#2-malformed-episode-data-handling)
3. [NULL/Empty Name Handling](#3-nullempty-name-handling)
4. [Bulk Update Unsaved Relations Fix](#4-bulk-update-unsaved-relations-fix)
5. [Memory Cleanup Improvements](#5-memory-cleanup-improvements)
6. [Stream Comparison Tool](#6-stream-comparison-tool)

---

## 1. Episode Deduplication Fix

**Commit:** 37cf643
**GitHub Issues:** #556, #569
**File:** apps/vod/tasks.py (batch_process_episodes function)

### Problem

When VOD providers send multiple streams for the same episode (e.g., same series/season/episode but different stream_ids), the code attempted to create multiple Episode objects with identical `(series_id, season_number, episode_number)` tuples, violating the unique constraint on the `vod_episode` table.

**Error example:**
```
ERROR: duplicate key value violates unique constraint
       "vod_episode_series_id_season_number__73053ba7_uniq"
DETAIL: Key (series_id, season_number, episode_number)=(11, 9, 2) already exists
```

### Root Cause

The batch processing logic didn't track episodes being created within the same batch. When processing 5 streams for the same episode:
- Stream 1: Creates `Episode(S09E02)` ✓
- Stream 2: Tries to create `Episode(S09E02)` again ✗ **CONSTRAINT VIOLATION**
- Streams 3-5: Same error

### Why This Happens

Providers may send multiple `stream_ids` for the same episode for various reasons:
- Different CDN endpoints
- Different subtitle/audio track options
- Backup streams
- Provider database inconsistencies
- Or simply duplicates with different IDs

### The Fix

Added batch-level episode tracking using a dictionary keyed by `(series_id, season_number, episode_number)`:

```python
batch_episodes = {}  # Track episodes in THIS batch
episode_key = (series.id, season_number, episode_number)

if episode_key in batch_episodes:
    # Reuse existing episode from this batch
    episode = batch_episodes[episode_key]
    logger.debug(f"Reusing episode from batch: {episode_name}")
else:
    # Create new episode (or fetch from DB)
    episode = existing_episodes.get(episode_key)
    if not episode:
        episode = Episode(...)
        episodes_to_create.append(episode)
    batch_episodes[episode_key] = episode
```

This ensures:
- **ONE** Episode object per (series, season, episode)
- **MULTIPLE** M3UEpisodeRelation objects (one per stream_id)

### Expected Behavior After Fix

For 5 streams of the same episode:
- Creates: 1 Episode object
- Creates: 5 M3UEpisodeRelation objects (each pointing to the same Episode)
- Logs: `"Reusing episode from batch: Episode Title (S09E02)"`

### Testing

1. Run VOD refresh with providers that send duplicate episode streams
2. Check logs for "Reusing episode from batch" messages
3. Verify database has 1 Episode with multiple M3UEpisodeRelation entries
4. Query: `SELECT episode_id, COUNT(*) FROM vod_m3uepisoderelation GROUP BY episode_id HAVING COUNT(*) > 1;`

---

## 2. Malformed Episode Data Handling

**Commit:** 7e78a1e
**File:** apps/vod/tasks.py (batch_process_episodes function)

### Problem

Some providers return malformed episode data structures that crash the import process.

**Expected format:**
```json
{
  "1": [episode1, episode2],
  "2": [episode3, episode4]
}
```
(dict organized by season number)

**Malformed format:**
```json
[episode1, episode2, episode3, episode4]
```
(flat list with no season organization)

**Error observed:**
```
ERROR: 'list' object has no attribute 'items'
```

**Impact:** This caused 337 series to import without any episodes.

### Root Cause

Code assumed `episodes_data` would always be a dict:

```python
for season_num, season_episodes in episodes_data.items():  # ✗ Crashes if list
```

### The Fix

Added `isinstance()` checks to handle both formats:

```python
if isinstance(episodes_data, dict):
    # Normal format: {"1": [...], "2": [...]}
    for season_num, season_episodes in episodes_data.items():
        for episode_data in season_episodes:
            episode_data['_season_number'] = int(season_num)
            all_episodes_data.append(episode_data)

elif isinstance(episodes_data, list):
    # Malformed format: [...]
    logger.warning(f"Provider returned episodes as list instead of dict for series {series.name}. "
                   f"Attempting to extract season numbers from episode data.")
    for episode_data in episodes_data:
        # Try to extract season from episode data itself
        season_num = episode_data.get('season_number') or episode_data.get('season') or 0
        episode_data['_season_number'] = int(season_num)
        all_episodes_data.append(episode_data)
```

### Fallback Strategy

When list format detected:
1. Log warning about malformed data
2. Attempt to extract `season_number` from individual episode objects
3. Fall back to season 0 if no season info available
4. Continue processing rather than crashing

### Impact

Fixed 337 series that previously imported without episodes.

---

## 3. NULL/Empty Name Handling

**Commit:** e803ced
**Files:**
- apps/vod/tasks.py (process_movie_batch, line 378)
- apps/vod/tasks.py (process_series_batch, line 691)
- apps/vod/tasks.py (batch_process_episodes, line 1309)

### Problem

Database constraint violations when providers send NULL or empty string values for movie/series/episode names.

**Error:**
```
ERROR: null value in column "name" of relation "vod_movie" violates
       not-null constraint
DETAIL: Failing row contains (79610, ..., null, ...)
```

### Root Cause

The previous code used Python's `dict.get()` with a default value:

```python
name = movie_data.get('name', 'Unknown')
```

This **ONLY** uses the default when the **KEY** is missing from the dictionary. If the key exists but the VALUE is NULL or empty string, it uses that value:

```python
movie_data = {'name': None}
name = movie_data.get('name', 'Unknown')  # Returns None, NOT 'Unknown' ✗

movie_data = {'name': ''}
name = movie_data.get('name', 'Unknown')  # Returns '', NOT 'Unknown' ✗
```

### Why Providers Send NULL Names

- Incomplete metadata from upstream sources
- API bugs returning partial data
- Database corruption at provider
- Missing TMDB/IMDB match resulting in empty fields

### The Fix

Use Python's `or` operator to handle both missing keys **AND** falsy values:

```python
# Movies
name = movie_data.get('name') or 'MovieNameNull'

# Series
name = series_data.get('name') or 'SeriesNameNull'

# Episodes
episode_name = episode_data.get('title') or 'EpisodeNameNull'
```

### How This Works

```python
movie_data = {}                          → 'MovieNameNull' (missing key)
movie_data = {'name': None}              → 'MovieNameNull' (None is falsy)
movie_data = {'name': ''}                → 'MovieNameNull' (empty string is falsy)
movie_data = {'name': 'Actual Movie'}    → 'Actual Movie' (truthy value used) ✓
```

### Chosen Naming Convention

- `MovieNameNull` (not "Unknown Movie")
- `SeriesNameNull` (not "Unknown Series")
- `EpisodeNameNull` (not "Unknown Episode")

This makes it obvious in the database/UI that the provider sent bad data, rather than looking like a legitimate title.

### Testing

1. Trigger VOD refresh with provider that sends incomplete metadata
2. Verify items import successfully with `*NameNull` placeholders
3. Check database for no NOT NULL constraint violations
4. Query: `SELECT name FROM vod_movie WHERE name LIKE '%NameNull';`

### Impact

- Prevents refresh failures when providers send malformed metadata
- Allows partial data import rather than complete batch failure

---

## 4. Bulk Update Unsaved Relations Fix

**Commit:** 334724a
**Files:**
- apps/vod/tasks.py (process_movie_batch, lines 658-661)
- apps/vod/tasks.py (process_series_batch, lines 995-998)

### Problem

Django ORM error during VOD refresh when trying to bulk_update relations that point to newly created (unsaved) movie/series objects.

**Error:**
```
ERROR: bulk_update() prohibited to prevent data loss due to unsaved
       related object 'movie'
```

This occurred even when the log showed:
```
INFO: Executing batch operations: 1 movies to create, 0 to update
```

The error happens during the `relations_to_update` step, not `movies_to_update`.

### Root Cause - The Scenario

1. Provider sends data for a **NEW** movie (doesn't exist in database yet)
2. Code creates `Movie` object and adds to `movies_to_create` list (no DB ID yet)
3. An **EXISTING** `M3UMovieRelation` needs to be updated to point to this new movie
4. Code does: `relation.movie = movie` (assigns unsaved Movie object)
5. Code adds relation to `relations_to_update` list
6. Later, `bulk_create` saves movies and gets their IDs
7. Code updates `relations_to_create` to use DB versions (this was working ✓)
8. Code tries `bulk_update(relations_to_update)` → **FAILS!** ✗

### Why It Fails

Django's `bulk_update` checks all foreign keys before executing. If any relation points to an unsaved object (no primary key), it rejects the entire operation to prevent data loss.

### The Disconnect

The code already had logic to fix this for NEW relations (`relations_to_create`):

```python
# This was working ✓
for relation in relations_to_create:
    if id(relation.movie) in created_movies:
        relation.movie = created_movies[id(relation.movie)]
```

But it forgot to do the same for UPDATED relations (`relations_to_update`):

```python
# This was missing ✗
for relation in relations_to_update:
    if id(relation.movie) in created_movies:
        relation.movie = created_movies[id(relation.movie)]
```

### The Fix

Added the same ID-mapping logic for `relations_to_update`:

```python
# After bulk_create of movies, re-fetch them with IDs
created_movies = {}  # Maps memory id(movie) → database Movie object

for movie in movies_to_create:
    if movie.tmdb_id:
        db_movie = Movie.objects.filter(tmdb_id=movie.tmdb_id).first()
    elif movie.imdb_id:
        db_movie = Movie.objects.filter(imdb_id=movie.imdb_id).first()
    else:
        db_movie = Movie.objects.filter(
            name=movie.name,
            year=movie.year,
            tmdb_id__isnull=True,
            imdb_id__isnull=True
        ).first()

    if db_movie:
        created_movies[id(movie)] = db_movie

# Fix relations_to_create (was already working)
for relation in relations_to_create:
    if id(relation.movie) in created_movies:
        relation.movie = created_movies[id(relation.movie)]

# Fix relations_to_update (THIS WAS MISSING)
for relation in relations_to_update:
    if id(relation.movie) in created_movies:
        relation.movie = created_movies[id(relation.movie)]

# Now bulk_update works because all relations point to saved objects
M3UMovieRelation.objects.bulk_update(relations_to_update, [...])
```

### Why Use id(object)?

Python's `id()` returns the memory address of an object. Since `bulk_create` doesn't update the original objects with their database IDs, we need to:

1. Remember which `Movie` object in memory corresponds to which in DB
2. Use `id(movie)` as a lookup key since we can't use `movie.id` (it's None)
3. Replace the in-memory Movie with the database Movie (which has an ID)

### Applied To

- `process_movie_batch()` at apps/vod/tasks.py:658-661
- `process_series_batch()` at apps/vod/tasks.py:995-998

### Testing

Trigger VOD refresh where:
- A new movie is created
- An existing relation needs to point to that new movie

Verify no "unsaved related object" errors occur.

### Impact

Fixes crash during VOD refresh when new movies/series are created and existing relations need to reference them.

---

## 5. Memory Cleanup Improvements

**Commit:** 8496ed8
**File:** apps/vod/tasks.py (batch_process_episodes function)

### Purpose

Prevent memory buildup during large VOD refreshes, especially in test environments with limited RAM.

**Observation:** Crash at 172MB during movie category refresh in test environment.

### What Was Added

```python
# Explicit cleanup to help garbage collection in low-memory environments
batch_episodes.clear()
episodes_to_update_set.clear()
del episodes_to_create, episodes_to_update, relations_to_create, relations_to_update
```

### Why This Helps

In Python, objects are reference-counted. By explicitly clearing dictionaries and deleting large lists after bulk operations, we:

- Release memory immediately rather than waiting for garbage collection
- Reduce memory pressure in containerized/limited-RAM environments
- Prevent OOM kills in Docker containers with strict memory limits

### Memory Usage Patterns

**Before:** Large batches accumulate in memory until function exit
**After:** Memory released immediately after `bulk_create`/`bulk_update`

### Testing

Monitor memory usage during large VOD refresh operations. Should see memory drop after each batch completion rather than accumulating.

---

## 6. Stream Comparison Tool

**Commits:** cab4119 (initial), 5b69141 (standalone), 535b391 (auto-discover)
**File:** compare_streams.py

### Evolution

#### Version 1: verify_stream_differences.py (cab4119)

- Django-based tool
- Required manual episode UUID input
- Module import issues in container
- **Abandoned** in favor of standalone version

#### Version 2: Standalone (5b69141)

- No Django dependency
- Direct database connection
- Still required manual stream URLs
- User reported errors
- **Replaced** with auto-discover version

#### Version 3: Auto-Discover (535b391) - **CURRENT**

Complete rewrite with automatic discovery and comprehensive analysis.

### Current Features

1. **Auto-discovery via Django ORM:**
   ```python
   duplicate_episodes = (
       M3UEpisodeRelation.objects
       .filter(m3u_account=account)
       .values('episode')
       .annotate(stream_count=Count('id'))
       .filter(stream_count__gt=1)      # Only episodes with 2+ streams
       .order_by('-stream_count')        # Most duplicates first
   )
   ```

2. **Django environment setup for container execution:**
   ```python
   os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
   django.setup()
   ```

3. **Stream analysis with ffprobe:**
   - Resolution, bitrate, codec, file size, FPS
   - Audio codec and channels
   - Duration

4. **Intelligent comparison:**
   - Allows 5% variance for bitrate/size (network fluctuations)
   - Flags streams as IDENTICAL or DIFFERENT
   - Provides detailed side-by-side comparison

### Usage

```bash
# Run from within Docker container
python compare_streams.py
```

No arguments required - automatically discovers and analyzes episodes with duplicate streams.

### Output Example

```
=== Scanning database for episodes with duplicate streams ===

Checking provider: ChicoTV
  Found 342 episodes with multiple streams
  Will analyze first 10 episodes

================================================================================
Episode: MasterChef Junior - S09E02 - Episode 2
Series: MasterChef Junior (2013)
Season 9, Episode 2
Provider: ChicoTV
Found 5 stream(s)
================================================================================

Analyzing stream 78025...
  ✓ Resolution: 1920x1080
  ✓ Codec: h264
  ✓ Bitrate: 5000 kbps
  ✓ File size: 2847.3 MB

Analyzing stream 78026...
  ✓ Resolution: 1920x1080
  ✓ Codec: h264
  ✓ Bitrate: 5012 kbps
  ✓ File size: 2853.1 MB

⚠️  WARNING: All streams appear IDENTICAL!
   Resolution: 1920x1080
   Bitrate:    5000 kbps
   Codec:      h264
   File size:  2847.3 MB

   These are likely DUPLICATES, not different quality versions.
   The provider may be sending the same stream with multiple IDs.

================================================================================
OVERALL SUMMARY
================================================================================
Total episodes analyzed: 10
Episodes with IDENTICAL streams: 8
Episodes with DIFFERENT streams: 2

⚠️  Warning: Some providers are sending duplicate streams with different IDs.
   This is the root cause of issue #556 and #569.
   The deduplication fix in apps/vod/tasks.py handles this correctly.
```

### Purpose

Verify that the episode deduplication fix is correctly handling providers that send multiple `stream_ids` for the same episode content.

### Benefits

- No manual intervention required
- Analyzes all providers systematically
- Provides clear evidence of duplicate vs quality variant streams
- Helps confirm fix is working correctly

---

## Summary of All Fixes

| Issue | Commit | Root Cause | Fix | Impact |
|-------|--------|------------|-----|--------|
| Episode duplicate key | 37cf643 | No batch-level tracking | Added `batch_episodes` dict | Prevents constraint violations |
| List has no attribute items | 7e78a1e | Assumed dict format | Added `isinstance()` checks | Fixed 337 series imports |
| NULL name constraint | e803ced | `.get()` doesn't handle NULL values | Used `or` operator | Prevents crashes on bad metadata |
| bulk_update unsaved object | 334724a | Forgot to update `relations_to_update` | Added ID mapping for both create/update | Prevents crash on new movies |
| Memory buildup | 8496ed8 | No explicit cleanup | Added `.clear()` and `del` | Reduces OOM risk |
| Stream verification | 535b391 | Manual process was error-prone | Auto-discovery tool | Easy verification of fix |

## Related Issues

- [#556](https://github.com/Dispatcharr/Dispatcharr/issues/556) - Duplicate key constraint on episodes
- [#569](https://github.com/Dispatcharr/Dispatcharr/issues/569) - MultipleObjectsReturned during playback

## Files Modified

- `apps/vod/tasks.py` - Core fixes for episode deduplication, NULL handling, bulk_update
- `compare_streams.py` - Stream comparison and verification tool
- `EPISODE_DEDUP_FIX.md` - User-facing documentation
- `FIXES_DETAILED.md` - This technical deep-dive document

---

*Document created: 2025-12-06*
*Branch: claude/debug-stream-generation-01XhVh1SQBWk6RBt5HXp612c*
