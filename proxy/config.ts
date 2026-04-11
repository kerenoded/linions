// Proxy configuration — tunable values for the local development proxy server.
// All values must have a comment explaining what they control.

/** TCP port the local proxy server listens on. Browser opens http://localhost:PORT */
export const PORT = 3000;

/** Local proxy route that serves the public viewer shell against repo-managed episodes. */
export const PREVIEW_BASE_PATH = "/preview";
