import { MAX_VIEWS, normalizeStatus, normalizeTour, normalizeViewRequest } from './worldModel.js';

/**
 * World view events (docs/WORLD_VIEW.md) into the store:
 * - `world_status` -> `worldStatus` (and its tour);
 * - `world_tour` -> `worldTour` (the tour bar);
 * - `world_view` -> queued in `worldViews`, with `worldFocus` set so CommandDeck opens the
 *   World page; the page posts it to the globe and answers world_view_result.
 * A disconnect drops queued views (the core has already given up on them).
 */
export function registerWorldEvents({ onSocket, store, unsubs }) {
  unsubs.push(onSocket('world_status', raw => {
    const status = normalizeStatus(raw);
    if (status) store.setState({ worldStatus: status, worldTour: status.tour });
  }));
  unsubs.push(onSocket('world_tour', raw => {
    const tour = normalizeTour(raw);
    if (tour) store.setState({ worldTour: tour });
  }));
  unsubs.push(onSocket('world_view', raw => {
    const request = normalizeViewRequest(raw);
    if (!request) return;
    store.setState(state => ({
      worldViews: [...(state.worldViews || []).filter(item => item.id !== request.id), request].slice(-MAX_VIEWS),
      worldFocus: request.id,
    }));
  }));
  unsubs.push(onSocket('disconnect', () => store.setState({ worldViews: [], worldFocus: null })));
}
