import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const virtualPython=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const python=existsSync(virtualPython)?virtualPython:(process.platform==='win32'?'python':'python3');
const child=spawn(python,process.argv.slice(2),{cwd:root,stdio:'inherit',windowsHide:true});
child.on('error',error=>{console.error('Cannot start Python:',error.message);process.exitCode=1;});
child.on('exit',code=>{process.exitCode=code??1;});
process.on('SIGINT',()=>child.kill('SIGINT'));
process.on('SIGTERM',()=>child.kill('SIGTERM'));
