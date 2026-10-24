import { useCallback, useReducer, useRef } from 'react';
import { createDraft, draftReducer } from './draft.js';
export function useRecipeDraft(initial) {
  const [state, dispatch] = useReducer(draftReducer, initial, createDraft);
  const version = useRef(0);
  const act = useCallback(action => { version.current++; dispatch(action); }, []);
  return { recipe: state.value, version, setRecipe: useCallback(value => act({ type: 'change', value }), [act]),
    resetRecipe: useCallback(value => act({ type: 'reset', value }), [act]),
    undo: () => act({ type: 'undo' }), redo: () => act({ type: 'redo' }),
    canUndo: state.past.length > 0, canRedo: state.future.length > 0 };
}
