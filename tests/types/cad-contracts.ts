import { createCadClient } from '../../src/transport/cadClient.ts';
import type { RpcSocket } from '../../src/transport/rpc.ts';
declare const socket: RpcSocket;
const cad = createCadClient(socket);
cad.call('cad_submit', { shape: 'scene', objects: [{ shape: 'box' }] });
cad.call('cad_plan', { prompt: 'A bracket' });
// @ts-expect-error CAD artifact formats exclude SVG.
cad.call('cad_artifact', { request_id: 'id', format: 'svg' });
// @ts-expect-error Plans require a prompt.
cad.call('cad_plan', {});
