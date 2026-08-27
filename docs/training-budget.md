# Seven-day training budget

The scheduler treats time and thermal limits as hard constraints:

- Hardware calibration first.
- Teacher labeling: at most 36 hours and 3–8 million accepted positions.
- Supervised training: at most 24 hours.
- Self-play and fine-tuning: at most 72 hours, using at most 12 CPU threads.
- Remaining time is reserved for quantization and strength matches.

Training pauses at 83 °C and resumes only after the GPU reaches 78 °C. Checkpoints are atomically written every 30 minutes. GPU allocation targets a 6.5 GiB soft limit and process RSS a 12 GiB ceiling.
