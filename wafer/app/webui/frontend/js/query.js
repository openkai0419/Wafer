import { getAspects, getItems, postQuery, ApiError } from './api.js';

let nextClientId = 1;

export class QueryClient {
  constructor(onExpired = () => {}) {
    this.id = nextClientId++;
    this.onExpired = onExpired;
    this.expired = false;
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

  async _expireOn404(request) {
    try {
      return await request;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404 && !this.expired) {
        this.expired = true;
        this.onExpired(this);
      }
      throw e;
    }
  }

  items(offset, limit) {
    return this._expireOn404(getItems(this.queryId, offset, limit));
  }

  aspects() {
    return this._expireOn404(getAspects(this.queryId));
  }
}
