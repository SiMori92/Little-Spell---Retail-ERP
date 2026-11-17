import 'server-only';
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
if(existsSync('.git')){const result=spawnSync('git',['config','core.hooksPath','.githooks'],{stdio:'inherit'});if(result.status!==0)process.exitCode=1;}
