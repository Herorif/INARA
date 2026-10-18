import { createImageClient } from '../../src/transport/imageClient.ts';
import type { RpcSocket } from '../../src/transport/rpc.ts';
declare const socket: RpcSocket;
const image = createImageClient(socket);
image.call('image_submit', { prompt: 'A pavilion' });
image.call('image_artifact', { request_id: 'id', format: 'png' });
// @ts-expect-error PNG/JSON are the image artifact formats.
image.call('image_artifact', { request_id: 'id', format: 'stl' });
// @ts-expect-error Prompt remains required by the generated server schema.
image.call('image_submit', { seed: 1 });
// @ts-expect-error This client cannot dispatch a different feature's event.
image.call('cad_submit', {});
