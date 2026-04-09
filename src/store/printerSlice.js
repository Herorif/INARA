export const createPrinterSlice = (set) => ({
    printerList: [],
    printerCount: 0,
    slicingStatus: { active: false, percent: 0, message: '' },
    activePrintStatus: null,

    setPrinterList: (list) => set({ printerList: list, printerCount: list.length }),
    setSlicingStatus: (val) => set({ slicingStatus: val }),
    setActivePrintStatus: (val) => set({ activePrintStatus: val }),

    updatePrinterStatus: (data) => {
        set(state => ({
            printerList: state.printerList.map(p =>
                p.name === data.printer ? { ...p, status: data } : p
            )
        }));
    },
});
