import assert from "node:assert/strict";
import test from "node:test";

import { GalleryController } from "../../frontend/src/gallery.js";
import { GeneratorController } from "../../frontend/src/generator.js";
import type { PlayerState } from "../../frontend/src/types.js";

type FakeLocalStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
};

function createFakeLocalStorage(): FakeLocalStorage {
  const store = new Map<string, string>();
  return {
    getItem(key: string): string | null {
      return store.get(key) ?? null;
    },
    setItem(key: string, value: string): void {
      store.set(key, value);
    },
    removeItem(key: string): void {
      store.delete(key);
    },
  };
}

test("gallery load handles thrown fetch errors gracefully", async () => {
  const originalFetch = globalThis.fetch;
  const container = {
    replaceChildrenCalled: false,
    replaceChildren(): void {
      this.replaceChildrenCalled = true;
    },
  };
  const statusLabel = { textContent: "" };
  globalThis.fetch = async () => {
    throw new Error("network down");
  };

  try {
    const gallery = new GalleryController({
      container: container as unknown as HTMLElement,
      statusLabel: statusLabel as unknown as HTMLElement,
      onSelectEpisode: () => undefined,
    });

    await gallery.load();

    assert.equal(statusLabel.textContent, "Failed to load gallery.");
    assert.equal(container.replaceChildrenCalled, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("generator polling handles thrown fetch errors gracefully", async () => {
  const originalFetch = globalThis.fetch;
  const originalLocalStorage = globalThis.localStorage;
  const originalWindow = globalThis.window;
  const fakeLocalStorage = createFakeLocalStorage();
  const promptInput = { disabled: true, value: "prompt" };
  const submitButton = { disabled: true };
  const stageLabel = { textContent: "" };
  const seenStates: PlayerState[] = [];
  let clearedIntervalHandle: number | null = null;

  globalThis.fetch = async () => {
    throw new Error("network down");
  };
  globalThis.localStorage = fakeLocalStorage as unknown as Storage;
  globalThis.window = {
    clearInterval(handle: number): void {
      clearedIntervalHandle = handle;
    },
  } as unknown as Window & typeof globalThis;

  try {
    fakeLocalStorage.setItem("linions.jobId", "job-123");
    const generator = new GeneratorController({
      form: { addEventListener: () => undefined } as unknown as HTMLFormElement,
      promptInput: promptInput as unknown as HTMLTextAreaElement,
      submitButton: submitButton as unknown as HTMLButtonElement,
      stageLabel: stageLabel as unknown as HTMLElement,
      onStateChange: (state) => {
        seenStates.push(state);
      },
      onEpisodeReady: () => undefined,
      onDraftKeyReady: () => undefined,
    }) as unknown as { pollHandle: number | null; pollStatus: (jobId: string) => Promise<void> };

    generator.pollHandle = 99;
    await generator.pollStatus("job-123");

    assert.equal(fakeLocalStorage.getItem("linions.jobId"), null);
    assert.equal(promptInput.disabled, false);
    assert.equal(submitButton.disabled, false);
    assert.equal(clearedIntervalHandle, 99);
    assert.deepEqual(seenStates.at(-1), {
      status: "error",
      message: "Status polling failed.",
    });
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.localStorage = originalLocalStorage;
    globalThis.window = originalWindow;
  }
});
