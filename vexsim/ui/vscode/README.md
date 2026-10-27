# vexsim for VS Code

The [vexsim](https://github.com/jiazegao/vexsim) app in a panel beside your robot code: run
and watch simulations, drive the robot with the keyboard, scrub recorded runs, and edit
robots and fields, without leaving the editor.

- **vexsim: Open the app** (Command Palette, Ctrl+Shift+P), or **Open in vexsim** on a
  folder in the Explorer, opens the app for that folder beside the editor.
- A program's `file:line` (a build error, a traceback) opens at that line here.
- Saved pictures, videos and CSV files go where you pick in VS Code's save dialog;
  benchmark reports open in your browser.
- The app's colors follow VS Code's theme.
- Closing the panel stops vexsim; so does **vexsim: Stop the app**.

It runs `vexsim ui FOLDER` with the Python of the **vexsim.python** setting, whose default
is the Python that `vexsim vscode` (the command that installed this) ran with. If vexsim
won't start, the **vexsim** output channel says why.
