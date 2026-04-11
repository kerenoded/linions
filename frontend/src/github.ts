export function buildGitHubProfileUrl(username: string): string {
  return `https://github.com/${encodeURIComponent(username)}`;
}
