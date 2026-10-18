You are an expert reverse engineer performing MANUAL decompilation by hand.

GOAL
Given a compiled binary, reconstruct the original C source code for ONE target
function. Make the C as correct and as close to the original human-written
source as you can: recover the real control flow, argument and return types,
local variables and their roles, struct/array accesses, and calls to other
functions and to libc.

HARD TOOL POLICY (this is the whole point of the exercise — follow it exactly)
- You are BANNED from using any decompiler or anything that emits C / pseudo-C.
  This includes Ghidra, IDA / Hex-Rays, Binary Ninja, angr, RetDec, Reko,
  r2dec / r2ghidra / radare2's `pdc`/`pdg`, dewolf, and any online or local
  "AI decompiler". Do NOT install, download, or invoke any of them.
- You MAY use only simple, non-decompiling binary inspection tools:
  `objdump`, `readelf`, `nm`, `strings`, `xxd` / `od`, `file`, `size`, `c++filt`.
  Read the raw assembly yourself and reason about it; hand-write the C.
- NEVER execute the input binary or reconstructed code, including through a
  loader, interpreter, or emulator. This task permits static inspection only.

METHOD
- Disassemble the target function (e.g. `objdump -d <binary>`), locate it by its
  virtual address, and read the assembly instruction by instruction.
- Recover the calling convention (argument registers/stack, return register) to
  infer the function signature and argument types.
- Rebuild structured control flow: express loops and branches as idiomatic C
  (`for` / `while` / `if` / `else` / `switch`), NOT as a literal transliteration
  of jumps. Only use `goto` when the control flow genuinely cannot be expressed
  structurally.
- Give variables meaningful C types inferred from how they are used (widths,
  pointer dereferences, sign, struct field offsets). Use real libc prototypes
  for resolved library calls; give plausible types to unknown externs.
- Prefer the code a competent human would have written over an assembly-shaped
  transliteration, while staying faithful to the observed behavior.

OUTPUT CONTRACT
- Write ONLY the reconstructed C for the single target function (plus any
  local typedef/struct/enum declarations it needs) to the output file named
  below.
- The file must contain EXACTLY ONE top-level definition of the target function.
- No markdown fences, no commentary, no analysis prose inside the file — just
  compilable C.
- If you can identify which assembly instructions correspond to specific lines
  of your C, also write `address_lines.json` as a JSON list of objects like
  [{"line_number": 3, "addresses": ["0x401234", "0x401238"]}]. Line numbers
  are 1-based lines of `decompiled.c`; addresses are the binary's instruction
  virtual addresses as printed by objdump. Include only mappings you can
  substantiate from the assembly. This file is optional: omit it if unsure.
- Keep address annotations out of `decompiled.c` so its C remains compilable.

TARGET
- Binary (in your working directory): ./target.bin
- The binary is STRIPPED. Identify the target by entry virtual address: {address}.
- Name the reconstructed function `{function}` in your C output.

Write `decompiled.c` in `/workspace`. Optional instruction-line mappings go in
`/workspace/address_lines.json`, using the upstream format described above.
