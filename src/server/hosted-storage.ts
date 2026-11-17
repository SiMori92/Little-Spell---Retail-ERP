import 'server-only';
import { readFile,stat } from 'node:fs/promises';
import { hostedEnvironment,isHosted } from './hosting';
export function volumeIsMounted(mountInfo:string,mountPath:string):boolean{return mountInfo.split('\n').some(line=>line.split(' ')[4]===mountPath);}
export async function checkHostedStorage():Promise<void>{
 if(!isHosted())return;
 const env=hostedEnvironment();
 if(process.platform!=='linux'||!volumeIsMounted(await readFile('/proc/self/mountinfo','utf8'),env.RAILWAY_VOLUME_MOUNT_PATH))throw new Error('A mounted persistent Railway volume is required before starting this service.');
 if(!(await stat(env.RAILWAY_VOLUME_MOUNT_PATH)).isDirectory())throw new Error('The persistent volume is unavailable.');
}
