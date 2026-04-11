import { resolvePublicUrl } from "./episode-loader.js";
import { buildGitHubProfileUrl } from "./github.js";
import type { GalleryEntry } from "./types.js";

type GalleryOptions = {
  container: HTMLElement;
  statusLabel: HTMLElement;
  onSelectEpisode: (episodePath: string) => void;
};

export class GalleryController {
  private readonly options: GalleryOptions;

  public constructor(options: GalleryOptions) {
    this.options = options;
  }

  public async load(): Promise<void> {
    this.options.statusLabel.textContent = "Loading gallery...";
    try {
      const response = await fetch(resolvePublicUrl("episodes/index.json"));
      if (!response.ok) {
        this.options.statusLabel.textContent = "Failed to load gallery.";
        this.options.container.replaceChildren();
        return;
      }

      const entries = (await response.json()) as GalleryEntry[];
      this.render(entries);
    } catch {
      this.options.statusLabel.textContent = "Failed to load gallery.";
      this.options.container.replaceChildren();
    }
  }

  private render(entries: GalleryEntry[]): void {
    this.options.container.replaceChildren();
    if (entries.length === 0) {
      this.options.statusLabel.textContent = "No published episodes yet.";
      return;
    }

    this.options.statusLabel.textContent = `${entries.length} episodes`;

    for (const entry of entries) {
      const card = document.createElement("article");
      card.className = "gallery-card";

      const thumbnail = document.createElement("img");
      thumbnail.src = resolvePublicUrl(entry.thumbPath);
      thumbnail.alt = `${entry.title} thumbnail`;
      thumbnail.loading = "lazy";
      thumbnail.decoding = "async";
      thumbnail.className = "gallery-thumb";
      thumbnail.addEventListener("click", () => {
        this.options.onSelectEpisode(entry.path);
      });

      const title = document.createElement("h3");
      title.textContent = entry.title;
      title.className = "gallery-title";
      title.addEventListener("click", () => {
        this.options.onSelectEpisode(entry.path);
      });

      const author = document.createElement("p");
      author.className = "gallery-author";

      const authorLink = document.createElement("a");
      authorLink.className = "github-link";
      authorLink.href = buildGitHubProfileUrl(entry.username);
      authorLink.target = "_blank";
      authorLink.rel = "noreferrer";
      authorLink.textContent = `@${entry.username}`;
      author.appendChild(authorLink);

      const description = document.createElement("p");
      description.className = "gallery-description";
      description.textContent = entry.description;

      card.append(thumbnail, author, title, description);
      this.options.container.appendChild(card);
    }
  }
}
