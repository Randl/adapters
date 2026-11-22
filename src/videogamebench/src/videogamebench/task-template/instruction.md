{game_prompt}

Control the game through screenshots and actions with `python /opt/game/play.py`.
Running it without arguments saves the current view to `/workspace/screen.png`.
Open that file with your image-viewing tool. The platform is {emulator}; the mode
is {mode}. Lite pauses during deliberation; real-time continues running.

For Game Boy, use `--buttons RIGHT A` (buttons: A, B, START, SELECT, UP, DOWN,
LEFT, RIGHT), or `--no-op`. For DOS, use `--action` with JSON, for example
`--action '{"action":"press_key","action_input":"ArrowRight"}'`.
DOS actions are click, move, drag, scroll_down, scroll_up, write, press_key and
hold_key. Move/drag inputs are "x,y" coordinates; key inputs use Playwright key
names. Game Boy actions use {action_frames} frames (the emulator also ticks on
button updates). The session permits {max_steps} evaluator steps.

Play toward the game's objectives. Your actions are recorded automatically.
Finish with `python /opt/game/play.py --finish`. No score file or textual answer
is required. Use only the visual control interface to interact with the game.
