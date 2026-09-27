- **The VS Code extension activates on a current project again.** Its
  activation glob and its project-root walk both looked for `refdes.yaml`,
  which is retired, so in a project holding `refdes-project.yaml` the
  extension never activated and a command that needed a root could only say
  it found no config file. `editors/vscode/package.json`'s `activationEvents`
  is now `workspaceContains:**/refdes-project.yaml`, `findRoot()` in
  `editors/vscode/extension.js` walks up to `refdes-project.yaml`, and the
  warning reads "Refdes: no refdes-project.yaml found." Nothing to change in
  your project — the fix is entirely on the extension's side.
