// Run by bundled Node outside ASAR. The pipe closes if the desktop supervisor dies.
const { pathToFileURL } = require('node:url');
process.stdin.resume();
process.stdin.on('end', () => process.exit(0));
process.stdin.on('error', () => process.exit(1));
import(pathToFileURL(process.argv[2]).href).catch((error) => {
  console.error(error);
  process.exit(1);
});
