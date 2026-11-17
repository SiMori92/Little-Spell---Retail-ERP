export function checkNode(): void {
  if (process.versions.node.split('.')[0] !== '22') {
    console.error('Little Spell requires Node 22. Select it with nvm use, then run corepack enable.');
    process.exit(1);
  }
}
checkNode();
