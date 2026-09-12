// Production build environment (replaced via angular.json `fileReplacements`).
// The hostname is resolved at runtime so the same bundle works on localhost and
// on any LAN address.
const host =
  typeof window !== 'undefined' && window.location?.hostname
    ? window.location.hostname
    : 'localhost';

export const environment = {
  production: true,
  apiBaseUrl: `http://${host}:8070`,
  wsBaseUrl: `ws://${host}:8070`,
};
