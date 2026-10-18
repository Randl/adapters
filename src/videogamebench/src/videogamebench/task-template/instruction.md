{game_prompt}

This task uses VideoGameBench Lite: the emulator pauses while you think. Use
`python /opt/game/play.py --buttons RIGHT` to act and save the resulting screenshot
at `/workspace/screen.png`. Multiple buttons can be pressed together, for example
`--buttons A RIGHT`. Use `--no-op` to advance without pressing a button, or omit
both flags to observe without advancing. Each action has the upstream default
15-frame duration. At most 15,000 actions are allowed.

The tool records the action sequence in `/workspace/actions.json`. Leave this file
as your submission. The verifier independently replays it from a fresh emulator
and checks the released checkpoints. Use the screenshot tool available to your
agent to view the screen; raw memory and emulator introspection are outside the
benchmark's visual interaction contract.
