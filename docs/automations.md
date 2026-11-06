# Break notifications

RunPee emits `runpee_break` when normal playback crosses into a bathroom window. It does not send notifications itself. Replace the notification action below with your own:

```yaml
alias: Movie bathroom break
triggers:
  - trigger: event
    event_type: runpee_break
actions:
  - action: notify.mobile_app_YOUR_PHONE
    data:
      title: Movie break
      message: >-
        {{ trigger.event.data.title }}:
        {{ trigger.event.data.duration_seconds }} seconds.
        Cue: {{ trigger.event.data.cue }}
```

With multiple players, add an `event_data` filter under the trigger. Use the actual linked entity, for example:

```yaml
triggers:
  - trigger: event
    event_type: runpee_break
    event_data:
      media_player: media_player.movie_room_cast
```

Alternatively, filter by the RunPee config-entry ID using `event_data.entry_id`.

Events occur at the window start, not in advance. Attaching inside a window, resuming from pause, or a detected seek re-anchors event tracking rather than sending catch-up notifications. Players do not reliably expose every seek, so not every position discontinuity can be classified. Recommended-only filtering and timing offsets apply to events as well as entities.

[Back to the README](../README.md)
