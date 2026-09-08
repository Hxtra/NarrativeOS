# Channel Profile Pattern

Treat a channel master prompt as a versioned production constitution, not a renderer prompt. Keep these fields configurable:

```json
{
  "channel_id": "example",
  "profile_version": "v001",
  "narrative": {"voice": [], "acts": [], "pattern_interrupt_interval_seconds": 180},
  "visual": {"aspect_ratio": "16:9", "visual_grammar": [], "forbidden": []},
  "audio": {"narration_style": "", "music_policy": "", "ducking_db": -12},
  "captions": {"style": "", "safe_area": true},
  "qa": {"required_checks": []}
}
```

Load only relevant rules at each stage. Enforce structural requirements with validators rather than relying on a long prompt being remembered. Separate audio segments, visual beats, and shots; they are not always one-to-one.
