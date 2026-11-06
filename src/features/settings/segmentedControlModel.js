// Pure mapping for SegmentedControl: one radio per option, checked when it is the value.

/** [{ id, label, checked }] for the given options and the selected value. */
export function segmentItems(options, value) {
  return (Array.isArray(options) ? options : []).map((option) =>
    ({ id: option.id, label: option.label, checked: option.id === value }));
}
