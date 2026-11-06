# Matching and timing

## Player compatibility

Choose the entity exposing the movie's title and playback position, not just the screen's power or active app. In **Developer tools → States**, look for `media_title`, `media_position`, and `media_position_updated_at`. A release year helps distinguish remakes; app names, stream URLs, and channel names are not useful movie titles.

Plex over Google Cast has been verified with real playback: matching, countdowns, active windows, break events, and pause behavior. Other players are unverified and depend on the metadata they expose. An Android TV/ADB entity may expose only power or app state while a separate Cast entity exposes playback metadata.

Explicit music and episodic metadata is excluded. Plex Cast sometimes labels movies as `tvshow`; matching is allowed for that app only when series, season, and episode fields are absent. An episode missing those fields cannot always be distinguished from a movie.

## Timing options

Use **Configure** on the integration entry:

- **Recommended windows only** (`recommended_windows_only`) filters windows for both entities and events.
- **Timing offset** (`timing_offset_seconds`, −3600 to +3600) adjusts for pre-roll or edition differences. **Positive delays windows; negative advances them.** With `movie_position = player_position - offset`, a +60-second offset moves a window at movie position 600 to player position 660.

Countdowns advance locally at 1× playback and freeze while paused. Missing position, an invalid position timestamp, or non-1× playback makes timing unavailable—not zero. Current-window remaining is zero outside a window when timing is valid. Upcoming windows excludes the current window.

Check the movie's synchronization cue. Trailers, alternate cuts, and inaccurate timestamps can shift timing; a window is not a guarantee that a scene is safe to miss. Synopses are omitted, and provider-marked content warnings are excluded from bathroom windows.

## Manual selection

Automatic matching requires a unique normalized title match, filtered by release year when available. Ambiguous results are not guessed. Inspect the **Status** sensor's `candidates` attribute, then use **Developer tools → Actions → RunPee: Select movie**:

```yaml
action: runpee.select_movie
data:
  entry_id: YOUR_RUNPEE_ENTRY_ID
  movie_id: 987 # Replace with a RunPee ID from the candidates.
```

Select the entry in the visual editor. `entry_id` is a Home Assistant config-entry ID, not an entity ID; `movie_id` is a RunPee identifier, not an IMDb or TMDB ID. The override lasts for the current content and clears when content changes or playback ends. Use `runpee.clear_movie_override` with the same `entry_id` to return to automatic matching.

The response actions `runpee.search_movies` (`entry_id`, `query`) and `runpee.get_peetimes` (`entry_id`, optional `movie_id`) look up data without changing the match. `get_peetimes` uses the current match when its movie ID is omitted.

## Events and notifications

The **`runpee_break`** event fires at a normal playback crossing into a window, not in advance. Attaching inside a window or a detected seek does not generate a catch-up notification. Players do not reliably expose every seek.

See the [notification example](automations.md), including filtering by player when you have multiple entries. The integration never sends notifications or controls playback itself.

## Privacy

Requests send search titles/movie IDs and the server's IP address to RunPee's undocumented web API. No RunPee account or API key is needed. Responses are cached and requests paced, with backoff on failures and rate limits; local countdown updates make no cloud requests.

Player associations and matched titles may appear in Home Assistant state, recorder history, backups, and automation traces. Consider recorder exclusions for countdowns or sensitive viewing history. Do not post real viewing history or full provider responses in issues.
