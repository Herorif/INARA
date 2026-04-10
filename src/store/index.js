import { create } from 'zustand';

import { createConnectionSlice } from './connectionSlice';
import { createChatSlice } from './chatSlice';
import { createAudioSlice } from './audioSlice';
import { createDeviceSlice } from './deviceSlice';
import { createUiSlice } from './uiSlice';
import { createCadSlice } from './cadSlice';
import { createBrowserSlice } from './browserSlice';
import { createKasaSlice } from './kasaSlice';
import { createPrinterSlice } from './printerSlice';
import { createVideoSlice } from './videoSlice';
import { createPhoneSlice } from './phoneSlice';
import { createReminderSlice } from './reminderSlice';

const useStore = create((...args) => ({
    ...createConnectionSlice(...args),
    ...createChatSlice(...args),
    ...createAudioSlice(...args),
    ...createDeviceSlice(...args),
    ...createUiSlice(...args),
    ...createCadSlice(...args),
    ...createBrowserSlice(...args),
    ...createKasaSlice(...args),
    ...createPrinterSlice(...args),
    ...createVideoSlice(...args),
    ...createPhoneSlice(...args),
    ...createReminderSlice(...args),
}));

export default useStore;
