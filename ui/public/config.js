// Where the UI finds the two services. These are the local (compose) values.
// The CD pipeline overwrites this file in dist/ with the Azure Container Apps URLs.
window.APP_CONFIG = {
  CATALOG_URL: 'http://localhost:8001',
  MATCHES_URL: 'http://localhost:8002',
}
