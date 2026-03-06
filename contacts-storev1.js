// contacts-store.js
// Shared localStorage layer for category + tag metadata.
// Both index.html and table.html import this via <script src="contacts-store.js">

const STORE_KEY = 'egm_contact_meta';

window.ContactStore = {
  // Return full map: { "email@x.com": { category: "internal"|"external"|"", tag: "" } }
  load() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); }
    catch { return {}; }
  },

  save(map) {
    localStorage.setItem(STORE_KEY, JSON.stringify(map));
  },

  get(email) {
    const m = this.load();
    return m[email] || { category: '', tag: '' };
  },

  set(email, fields) {
    const m = this.load();
    m[email] = { ...(m[email] || { category: '', tag: '' }), ...fields };
    this.save(m);
  },

  // Bulk update from table — pass full map
  replace(map) { this.save(map); },
};
