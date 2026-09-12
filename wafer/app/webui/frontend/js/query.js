import { getAspects, getItems, postQuery, ApiError } from './api.js';

let nextClientId = 1;

export class QueryClient {
  constructor() {
    this.id = nextClientId++;
    this.db = '';
    this.filters = [];
    this.sort = 'name';
    this.ascending = true;
    this.queryId = '';
    this.total = 0;
  }

  async run(db, filters, sort, ascending) {
    this.db = db;
    this.filters = filters;
    this.sort = sort;
    this.ascending = ascending;
    const result = await postQuery(db, filters, sort, ascending);
    this.queryId = result.query_id;
    this.total = result.total;
    return result;
  }

  async _withRetry(fn) {
    try {
      return await fn(this.queryId);
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 404) throw e;
      const result = await postQuery(this.db, this.filters, this.sort, this.ascending);
      this.queryId = result.query_id;
      this.total = result.total;
      return fn(this.queryId);
    }
  }

  items(offset, limit) {
    return this._withRetry((queryId) => getItems(queryId, offset, limit));
  }

  aspects() {
    return this._withRetry((queryId) => getAspects(queryId));
  }
}
